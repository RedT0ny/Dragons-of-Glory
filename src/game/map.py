import heapq
from collections import defaultdict

from src.content.loader import load_countries_yaml
from src.content.specs import HexDirection, HexsideType, UnitType, UnitRace, LocType, TerrainType


class Hex:
    """
    Represents a hexagon using axial coordinates (q, r).
    Includes methods for offset conversion and mathematical calculations.
    """
    def __init__(self, q, r):
        self.q = q
        self.r = r
        self.attacked_this_turn = False

    @property
    def s(self):
        """Implicit cube coordinate: q + r + s = 0"""
        return -self.q - self.r

    def axial_to_offset(self):
        """Converts axial (q, r) to offset (col, row) for the rectangular map."""
        # Asumiendo 'pointy top' y 'odd-r' (común en mapas rectangulares)
        col = self.q + (self.r - (self.r & 1)) // 2
        row = self.r
        return col, row

    @staticmethod
    def offset_to_axial(col, row):
        """Converts offset (col, row) to axial (q, r)."""
        q = col - (row - (row & 1)) // 2
        r = row
        return Hex(q, r)

    def __add__(self, other):
        return Hex(self.q + other.q, self.r + other.r)

    def neighbors(self):
        """
        Returns the 6 neighboring hexagons using axial (q, r) offsets
        for a pointy-top grid.
        Ordered: [E, SE, SW, W, NW, NE] to match View indices 0..5
        """
        # Mapping our Enum to logical coordinate offsets
        # Order matters for the View loop!
        ordered_offsets = [
            Hex(1, 0),   # 0: E
            Hex(0, 1),   # 1: SE
            Hex(-1, 1),  # 2: SW
            Hex(-1, 0),  # 3: W
            Hex(0, -1),  # 4: NW
            Hex(1, -1)   # 5: NE
        ]
        return [self + offset for offset in ordered_offsets]

    def distance_to(self, other):
        """Cálculo de distancia Manhattan para hexágonos."""
        return (abs(self.q - other.q) + 
                abs(self.q + self.r - other.q - other.r) + 
                abs(self.r - other.r)) // 2

    def __repr__(self):
        col, row = self.axial_to_offset()
        return f"Hex(Axial:{self.q},{self.r} | Offset:{col:02d}{row:02d})"

    def __eq__(self, other):
        if not isinstance(other, Hex):
            return False
        return self.q == other.q and self.r == other.r

    def __lt__(self, other):
        return (self.q, self.r) < (other.q, other.r)

    def __hash__(self):
        return hash((self.q, self.r))


class Board:
    """
    The Game Board model (Single Source of Truth).
    Manages the grid of hexes, terrain, boundaries, and unit spatial tracking.
    """
    def __init__(self, width, height, offset_col=0, offset_row=0):
        self.width = width
        self.height = height
        # offset_col and offset_row represent the local (0,0) origin on the master map.
        # These offsets are in offset (col, row) coordinates.
        self.offset_col = offset_col
        self.offset_row = offset_row

        self.grid = {}  # (q, r) -> terrain_type
        self.hexside_data = {}  # ((q1,r1), (q2,r2)) -> border_type
        # Add a way to quickly find which hexsides are rivers
        self.navigable_edges = set()
        self.unit_map = defaultdict(list)
        self.locations = {} # (q, r) -> dict (location data)

    def populate_terrain(self, terrain_data: dict):
        """
        Populates the grid from a dict of 'col,row' -> 'terrain_type'.
        Designed to work with loader.load_terrain_csv output.
        """
        for key, terrain in terrain_data.items():
            try:
                col_str, row_str = key.split(',')
                col, row = int(col_str), int(row_str)

                # Convert offset (col, row) to axial (q, r)
                hex_obj = Hex.offset_to_axial(col, row)
                self.grid[(hex_obj.q, hex_obj.r)] = terrain
            except ValueError:
                continue

    def populate_locations(self, special_locs: list, countries: dict):
        """
        Populates locations from config and country capitals.
        """
        # 1. Add special locations (Ruins, etc)
        for loc_spec in special_locs:
            if loc_spec.coords:
                col, row = loc_spec.coords
                hex_obj = Hex.offset_to_axial(col, row)
                self.locations[(hex_obj.q, hex_obj.r)] = {
                    'type': loc_spec.loc_type,
                    'is_capital': False,
                    'country_id': None,
                    'location_id': loc_spec.id,
                    'occupier': None,
                }

        # 2. Add country locations (Cities, Capitals) - Override if conflict?
        for country in countries.values():
            # Handle cases where locations is a dict (runtime object) vs list (spec)
            country_locations = country.locations.values() if isinstance(country.locations, dict) else country.locations

            for loc_spec in country_locations:
                if loc_spec.coords:
                    col, row = loc_spec.coords
                    hex_obj = Hex.offset_to_axial(col, row)
                    # Merge or overwrite
                self.locations[(hex_obj.q, hex_obj.r)] = {
                    'type': loc_spec.loc_type,
                    'is_capital': loc_spec.is_capital,
                    'country_id': country.id,
                    'location_id': loc_spec.id,
                    'occupier': None,
                }

    def populate_hexsides(self, hexsides_data: dict):
        """
        Populates hexsides from the config dictionary (loader.load_map_config).
        Format: {'river': [[col, row, dir_str], ...], ...}
        """
        # Map string directions to indices for Hex.neighbors() [E, SE, SW, W, NW, NE]
        dir_str_map = {
            "E": 0, "SE": 1,
            "SW": 2, "W": 3, "NW": 4, "NE": 5
        }

        for side_type, entries in hexsides_data.items():
            for col, row, direction_str in entries:
                dir_idx = dir_str_map.get(direction_str)
                if dir_idx is not None:
                    self.add_hexside_by_offset(col, row, dir_idx, side_type)

    def add_hexside(self, q1, r1, q2, r2, side_type):
        """Registers a special border between two hexes (River/Mountain)."""
        key = tuple(sorted([(q1, r1), (q2, r2)]))
        self.hexside_data[key] = side_type

        # Rule 4: Ships can only move along Deep Rivers.
        # Fords and Bridges are for ground units and usually block large ships.
        if self._hexside_is(side_type, HexsideType.DEEP_RIVER):
            self.navigable_edges.add(key)

    @staticmethod
    def _hexside_is(value, hexside_type: HexsideType) -> bool:
        if isinstance(value, HexsideType):
            return value == hexside_type
        return value == hexside_type.value

    def add_unit_to_spatial_map(self, unit):
        """Registers a unit at its current position in the spatial lookup."""
        if not hasattr(unit, 'position') or not unit.position:
            return

        # unit.position is (col, row). We store by axial (q, r) internally or offset?
        # get_units_in_hex uses (q, r) inputs, but let's check what game_state passes.
        # game_state.move_unit passes target_hex which is Hex(axial).
        # But unit.position stores offset (col, row) usually for serialization.

        # Let's standardize: unit.position is (col, row) offset.
        # Spatial map keys will be (q, r) axial for math efficiency.

        col, row = unit.position
        hex_obj = Hex.offset_to_axial(col, row)
        key = (hex_obj.q, hex_obj.r)

        if unit not in self.unit_map[key]:
            self.unit_map[key].append(unit)

    def remove_unit_from_spatial_map(self, unit):
        """Removes a unit from the spatial lookup."""
        if not hasattr(unit, 'position') or not unit.position:
            # Fallback: unit may have cleared its position before removal.
            for key, units in list(self.unit_map.items()):
                if unit in units:
                    units.remove(unit)
                    if not units:
                        del self.unit_map[key]
                    break
            return

        col, row = unit.position

        # Fix: Ensure position coordinates are valid integers before converting
        if col is None or row is None:
            for key, units in list(self.unit_map.items()):
                if unit in units:
                    units.remove(unit)
                    if not units:
                        del self.unit_map[key]
                    break
            return

        hex_obj = Hex.offset_to_axial(col, row)
        key = (hex_obj.q, hex_obj.r)

        if key in self.unit_map:
            if unit in self.unit_map[key]:
                self.unit_map[key].remove(unit)

    def is_ship_bridge(self, from_hex, to_hex, alliance):
        """
        Rule 4: A ship in a river hexside acts as a bridge for
        friendly armies during any Turn in which it does not move.
        """
        key = tuple(sorted([(from_hex.q, from_hex.r), (to_hex.q, to_hex.r)]))

        # 1. Must be a deep_river to have a ship there
        if key not in self.navigable_edges:
            return False

        # 2. Check all units in the two adjacent hexes
        for hex_coord in [from_hex, to_hex]:
            units = self.get_units_in_hex(hex_coord.q, hex_coord.r)
            for u in units:
                if u.unit_type == UnitType.FLEET and u.allegiance == alliance:
                    # Check if this ship is stationed on THIS specific hexside
                    if getattr(u, 'river_hexside', None) == key and not getattr(u, "moved_this_turn", False):
                        return True
        return False

    def add_hexside_by_offset(self, col, row, direction_idx, side_type):
        """
        Helper for config loading.
        Takes offset (col, row) and a direction (0-5) to find the neighbor.
        """
        origin = Hex.offset_to_axial(col, row)
        neighbor = origin.neighbors()[direction_idx]
        self.add_hexside(origin.q, origin.r, neighbor.q, neighbor.r, side_type)

    def to_master_coords(self, q, r):
        """Converts local scenario coordinates (axial) to master map coordinates (axial)."""
        col, row = Hex(q, r).axial_to_offset()
        master_col = col + self.offset_col
        master_row = row + self.offset_row
        master_hex = Hex.offset_to_axial(master_col, master_row)
        return master_hex.q, master_hex.r

    def get_terrain(self, hex_coord) -> TerrainType:
        """Returns the logical terrain type as a TerrainType Enum."""
        master_q, master_r = self.to_master_coords(hex_coord.q, hex_coord.r)
        raw_terrain = self.grid.get((master_q, master_r), "plain")

        # Strip 'c_' prefix if it exists
        if raw_terrain.startswith("c_"):
            raw_terrain = raw_terrain[2:]

        # Convert string to Enum object
        try:
            return TerrainType(raw_terrain)
        except ValueError:
            # Fallback for unknown terrain
            return TerrainType.GRASSLAND

    def is_coastal(self, hex_coord):
        """Helper to specifically check for coastal rules."""
        master_q, master_r = self.to_master_coords(hex_coord.q, hex_coord.r)
        raw_terrain = self.grid.get((master_q, master_r), "")
        return raw_terrain.startswith("c_")

    def get_hexside(self, from_hex, to_hex):
        m1_q, m1_r = self.to_master_coords(from_hex.q, from_hex.r)
        m2_q, m2_r = self.to_master_coords(to_hex.q, to_hex.r)
        key = tuple(sorted([(m1_q, m1_r), (m2_q, m2_r)]))
        return self.hexside_data.get(key)

    def get_hexside_key(self, from_hex, to_hex):
        m1_q, m1_r = self.to_master_coords(from_hex.q, from_hex.r)
        m2_q, m2_r = self.to_master_coords(to_hex.q, to_hex.r)
        return tuple(sorted([(m1_q, m1_r), (m2_q, m2_r)]))

    def get_effective_hexside(self, from_hex, to_hex):
        """
        Returns the gameplay-effective hexside type.
        Rule: all six hexsides adjacent to a mountain hex are treated as mountain,
        except when explicitly defined as a pass.
        """
        raw = self.get_hexside(from_hex, to_hex)
        if self._hexside_is(raw, HexsideType.PASS):
            return raw

        if (
            self.get_terrain(from_hex) == TerrainType.MOUNTAIN
            or self.get_terrain(to_hex) == TerrainType.MOUNTAIN
        ):
            return HexsideType.MOUNTAIN.value

        return raw

    @staticmethod
    def _fleet_state_key(state):
        hex_obj, river_hexside = state
        return (hex_obj.q, hex_obj.r, river_hexside)

    def _local_hex_from_master_coords(self, master_q, master_r):
        master_col, master_row = Hex(master_q, master_r).axial_to_offset()
        local_col = master_col - self.offset_col
        local_row = master_row - self.offset_row
        return Hex.offset_to_axial(local_col, local_row)

    def _river_endpoints_local(self, river_hexside):
        if not river_hexside:
            return []
        (q1, r1), (q2, r2) = river_hexside
        return [
            self._local_hex_from_master_coords(q1, r1),
            self._local_hex_from_master_coords(q2, r2),
        ]

    def _is_valid_local_hex(self, hex_obj):
        col, row = hex_obj.axial_to_offset()
        return 0 <= col < self.width and 0 <= row < self.height

    def is_valid_hex(self, hex_obj):
        """Compatibility wrapper used by older BFS helpers."""
        return self._is_valid_local_hex(hex_obj)

    def _is_enemy_for_fleet(self, unit, other):
        return (
            other.allegiance != unit.allegiance
            and other.allegiance != "neutral"
            and getattr(other, "is_on_map", True)
        )

    def _hex_has_enemy_unit_for_fleet(self, hex_obj, unit):
        for other in self.get_units_in_hex(hex_obj.q, hex_obj.r):
            if self._is_enemy_for_fleet(unit, other):
                return True
        return False

    def _hexside_has_enemy_ship(self, river_hexside, unit):
        for units in self.unit_map.values():
            for other in units:
                if (
                    other is not unit
                    and getattr(other, "unit_type", None) == UnitType.FLEET
                    and getattr(other, "river_hexside", None) == river_hexside
                    and self._is_enemy_for_fleet(unit, other)
                ):
                    return True
        return False

    def _fleet_count_on_river_hexside(self, river_hexside, exclude_unit=None):
        count = 0
        for units in self.unit_map.values():
            for other in units:
                if other is exclude_unit:
                    continue
                if (
                    getattr(other, "unit_type", None) == UnitType.FLEET
                    and getattr(other, "river_hexside", None) == river_hexside
                    and getattr(other, "is_on_map", True)
                ):
                    count += 1
        return count

    def _fleet_can_enter_hex(self, unit, hex_obj):
        if not self._is_valid_local_hex(hex_obj):
            return False
        if self._hex_has_enemy_unit_for_fleet(hex_obj, unit):
            return False
        loc = self.get_location(hex_obj)
        if loc and isinstance(loc, dict) and loc.get("type") == LocType.PORT.value:
            return True
        terrain = self.get_terrain(hex_obj)
        return terrain in (TerrainType.OCEAN, TerrainType.MAELSTROM) or self.is_coastal(hex_obj)

    def _fleet_can_enter_river_hexside(self, unit, river_hexside):
        if self._hexside_has_enemy_ship(river_hexside, unit):
            return False

        endpoints = self._river_endpoints_local(river_hexside)
        if len(endpoints) != 2:
            return False

        if not all(self._is_valid_local_hex(h) for h in endpoints):
            return False

        if any(self._hex_has_enemy_unit_for_fleet(h, unit) for h in endpoints):
            return False

        return self._fleet_count_on_river_hexside(river_hexside, exclude_unit=unit) < 2

    def _fleet_neighbor_states(self, unit, state):
        current_hex, river_hexside = state
        neighbors = []

        if river_hexside is None:
            for next_hex in current_hex.neighbors():
                if not self._is_valid_local_hex(next_hex):
                    continue
                edge = self.get_effective_hexside(current_hex, next_hex)
                if self._hexside_is(edge, HexsideType.DEEP_RIVER):
                    next_side = self.get_hexside_key(current_hex, next_hex)
                    if not self._fleet_can_enter_river_hexside(unit, next_side):
                        continue
                    neighbors.append(((current_hex, next_side), 1))
                    neighbors.append(((next_hex, next_side), 1))
                    continue

                if self._fleet_can_enter_hex(unit, next_hex):
                    neighbors.append(((next_hex, None), 1))

            # Port special-case: a fleet in port may enter an adjacent deep-river
            # hexside formed by two neighboring hexes of the port.
            loc = self.get_location(current_hex)
            if loc and isinstance(loc, dict) and loc.get("type") == LocType.PORT.value:
                adjacent = [h for h in current_hex.neighbors() if self._is_valid_local_hex(h)]
                for i in range(len(adjacent)):
                    for j in range(i + 1, len(adjacent)):
                        a = adjacent[i]
                        b = adjacent[j]
                        edge = self.get_effective_hexside(a, b)
                        if not self._hexside_is(edge, HexsideType.DEEP_RIVER):
                            continue
                        side = self.get_hexside_key(a, b)
                        if not self._fleet_can_enter_river_hexside(unit, side):
                            continue
                        neighbors.append(((a, side), 1))
                        neighbors.append(((b, side), 1))
            return neighbors

        endpoints = self._river_endpoints_local(river_hexside)
        if len(endpoints) != 2:
            return neighbors
        a, b = endpoints
        if current_hex == a:
            neighbors.append(((b, river_hexside), 0))
        elif current_hex == b:
            neighbors.append(((a, river_hexside), 0))

        for endpoint in endpoints:
            if self._fleet_can_enter_hex(unit, endpoint):
                neighbors.append(((endpoint, None), 1))

            for next_hex in endpoint.neighbors():
                if not self._is_valid_local_hex(next_hex):
                    continue
                edge = self.get_effective_hexside(endpoint, next_hex)
                if self._hexside_is(edge, HexsideType.DEEP_RIVER):
                    continue
                if self._fleet_can_enter_hex(unit, next_hex):
                    neighbors.append(((next_hex, None), 1))

            for next_hex in endpoint.neighbors():
                if not self._is_valid_local_hex(next_hex):
                    continue
                edge = self.get_effective_hexside(endpoint, next_hex)
                if not self._hexside_is(edge, HexsideType.DEEP_RIVER):
                    continue
                next_side = self.get_hexside_key(endpoint, next_hex)
                if next_side == river_hexside:
                    continue
                if not self._fleet_can_enter_river_hexside(unit, next_side):
                    continue
                neighbors.append(((endpoint, next_side), 1))
                neighbors.append(((next_hex, next_side), 1))
        return neighbors

    def find_fleet_route(self, unit, start_hex, target_hex):
        """
        Finds minimum-MP route for fleets using hex/hexside state.
        Returns (state_path, cost), where state_path includes start and end states.
        """
        start_state = (start_hex, getattr(unit, "river_hexside", None))
        start_key = self._fleet_state_key(start_state)
        frontier = []
        heapq.heappush(frontier, (0, 0, start_state))
        cost_so_far = {start_key: 0}
        came_from = {start_key: None}
        state_by_key = {start_key: start_state}
        counter = 1

        best_target_key = None
        best_target_cost = float("inf")

        while frontier:
            current_cost, _, current_state = heapq.heappop(frontier)
            current_key = self._fleet_state_key(current_state)
            if current_cost > cost_so_far.get(current_key, float("inf")):
                continue

            current_hex, _ = current_state
            if current_hex == target_hex and current_cost < best_target_cost:
                best_target_key = current_key
                best_target_cost = current_cost

            for next_state, step_cost in self._fleet_neighbor_states(unit, current_state):
                next_key = self._fleet_state_key(next_state)
                new_cost = current_cost + step_cost
                if new_cost < cost_so_far.get(next_key, float("inf")):
                    cost_so_far[next_key] = new_cost
                    came_from[next_key] = current_key
                    state_by_key[next_key] = next_state
                    heapq.heappush(frontier, (new_cost, counter, next_state))
                    counter += 1

        if best_target_key is None:
            return [], float("inf")

        rev_keys = []
        node = best_target_key
        while node is not None:
            rev_keys.append(node)
            node = came_from.get(node)
        rev_keys.reverse()
        path = [state_by_key[k] for k in rev_keys]
        return path, best_target_cost

    def get_reachable_hexes_for_fleet(self, unit):
        if not getattr(unit, "position", None):
            return []
        start_hex = Hex.offset_to_axial(*unit.position)
        max_mp = getattr(unit, "movement_points", unit.movement)
        start_state = (start_hex, getattr(unit, "river_hexside", None))
        start_key = self._fleet_state_key(start_state)
        frontier = []
        heapq.heappush(frontier, (0, 0, start_state))
        cost_so_far = {start_key: 0}
        counter = 1
        reachable = set()

        while frontier:
            current_cost, _, state = heapq.heappop(frontier)
            state_key = self._fleet_state_key(state)
            if current_cost > cost_so_far.get(state_key, float("inf")):
                continue
            if current_cost > max_mp:
                continue

            current_hex, _ = state
            if current_hex != start_hex and self.can_stack_move_to([unit], current_hex):
                reachable.add(current_hex)

            for next_state, step_cost in self._fleet_neighbor_states(unit, state):
                new_cost = current_cost + step_cost
                if new_cost > max_mp:
                    continue
                next_key = self._fleet_state_key(next_state)
                if new_cost < cost_so_far.get(next_key, float("inf")):
                    cost_so_far[next_key] = new_cost
                    heapq.heappush(frontier, (new_cost, counter, next_state))
                    counter += 1

        return list(reachable)

    def get_location(self, hex_coord):
        """Returns location dict if one exists at this hex."""
        return self.locations.get((hex_coord.q, hex_coord.r))

    def get_units_in_hex(self, q, r):
        return self.unit_map.get((q, r), [])

    def can_stack_move_to(self, moving_units, target_hex):
        """
        Checks if a stack of units can end their movement in the target hex
        considering existing units and stacking limits.
        """
        if not moving_units:
            return True

        # 1. Enemy Check (Assumes all moving units share allegiance)
        # We check the first unit, as stacks are usually single-allegiance
        if self.has_enemy_army(target_hex, moving_units[0].allegiance):
            return False

        # 2. Combine moving stack with units ALREADY at destination
        # (Exclude any units that are part of the moving stack, just in case)
        existing = self.get_units_in_hex(target_hex.q, target_hex.r)
        others = [u for u in existing if u not in moving_units]

        combined_stack = others + moving_units

        # 3. Kender Rule
        # Kender Infantry cannot stack with Non-Kender Armies
        has_kender_army = any(u.race == UnitRace.KENDER and u.unit_type == UnitType.INFANTRY for u in combined_stack)
        has_normal_army = any(u.is_army() and not (u.race == UnitRace.KENDER and u.unit_type == UnitType.INFANTRY) for u in combined_stack)

        if has_kender_army and has_normal_army:
            return False

        # 4. Count Totals
        army_count = sum(1 for u in combined_stack if u.is_army())
        wing_count = sum(1 for u in combined_stack if u.unit_type == UnitType.WING)

        # 5. Check Limits
        # Base limits
        army_limit = 2
        wing_limit = 2

        # Fortified bonus (City, Port, Fortress, or Capital) increases army limit to 3
        loc = self.get_location(target_hex)
        if loc:
            is_fortified = (loc.get('is_capital') or
                            loc.get('type') in [LocType.CITY.value, LocType.PORT.value, LocType.FORTRESS.value])
            if is_fortified:
                army_limit = 3

        if army_count > army_limit:
            return False

        if wing_count > wing_limit:
            return False

        return True

    def can_unit_move_to(self, unit, target_hex):
        """
        Wrapper for single unit checks (used by deployment).
        """
        return self.can_stack_move_to([unit], target_hex)

    def can_unit_land_on_hex(self, unit, target_hex):
        """
        Checks if a unit can be placed on a given hex, for unboarding or deployment.
        This checks terrain restrictions only, not stacking or ZOC.
        """
        # Wings can fly over sea, but must start/end on land (including coastal).
        if unit.unit_type == UnitType.WING:
            terrain = self.get_terrain(target_hex)
            forbidden_terrain = {
                TerrainType.DESERT,
                TerrainType.OCEAN,
                TerrainType.MAELSTROM,
            }
            return terrain not in forbidden_terrain

        # Fleets can only be in water, ports or coastal hexes
        if unit.unit_type == UnitType.FLEET:
            is_coastal = self.is_coastal(target_hex)
            loc = self.get_location(target_hex)
            is_port = False
            if loc and isinstance(loc, dict):
                is_port = (loc.get('type') == LocType.PORT.value)

            return is_coastal or is_port

        # Ground units (Army, Leader, etc.)
        if unit.is_army() or unit.is_leader():
            terrain = self.get_terrain(target_hex)

            # General ground unit restrictions
            forbidden_terrain = [
                TerrainType.OCEAN,
                TerrainType.DESERT,
                TerrainType.SWAMP,
                TerrainType.MAELSTROM,
            ]
            if terrain in forbidden_terrain:
                return False

            return True

        # Default for any other types (e.g. Wizards)
        return True

    def has_enemy_army(self, hex_coord, alliance):
        """Rule 5: Check if hex contains any army from a different alliance."""
        units = self.get_units_in_hex(hex_coord.q, hex_coord.r)
        for u in units:
            if (
                u.allegiance != alliance
                and u.allegiance != 'neutral'
                and hasattr(u, "is_army")
                and u.is_army()
            ):
                return True
        return False

    def is_adjacent_to_enemy(self, hex_coord, unit):
        """Rule 5: Check ZOC proximity, respecting terrain barriers."""
        for neighbor in hex_coord.neighbors():
            if self.has_enemy_army(neighbor, unit.allegiance):
                hexside = self.get_effective_hexside(hex_coord, neighbor)
                # "Armies are never considered adjacent if separated by mountain or deep river"
                blocked = (
                    self._hexside_is(hexside, HexsideType.MOUNTAIN)
                    or self._hexside_is(hexside, HexsideType.DEEP_RIVER)
                )
                if not blocked:
                    return True
        return False

    def get_movement_cost(self, unit, from_hex, to_hex):
        """
        Dispatches to the correct movement logic based on unit class.
        """
        if unit.unit_type == UnitType.WIZARD:
            return 0  # Rule 5: Wizards ignore hex costs

        if unit.unit_type == UnitType.WING:
            return self._get_wing_movement_cost(unit, from_hex, to_hex)
        if unit.unit_type == UnitType.FLEET:
            # Pass unit to helper for enemy checks
            return self._get_fleet_movement_cost(unit, from_hex, to_hex)

        return self._get_ground_movement_cost(unit, from_hex, to_hex)

    def _get_wing_movement_cost(self, unit, from_hex, to_hex):
        """Rule 6: Flying creatures."""
        terrain = self.get_terrain(to_hex)
        if terrain == TerrainType.DESERT:
            return float('inf')  # Cannot enter desert

        cost = 1
        # It costs one extra Movement Point for an air army to fly over a mountain hexside.
        if self._hexside_is(self.get_effective_hexside(from_hex, to_hex), HexsideType.MOUNTAIN):
            cost += 1
        return cost

    def _get_fleet_movement_cost(self, unit, from_hex, to_hex):
        """
        Rule 4: Ships count hexsides moved along (deep rivers).
        Also checks for enemy ships/armies (Blocking) and Stacking.
        """
        # 1. Check for blocking enemies in the destination hex.
        if self._hex_has_enemy_unit_for_fleet(to_hex, unit):
            return float('inf')

        # 2. Check River Movement & Stacking
        # "Only two ships may be stacked in a river hexside."
        if self._hexside_is(self.get_effective_hexside(from_hex, to_hex), HexsideType.DEEP_RIVER):
            river_side = self.get_hexside_key(from_hex, to_hex)
            if self._hexside_has_enemy_ship(river_side, unit):
                return float('inf')
            if self._fleet_count_on_river_hexside(river_side, exclude_unit=unit) >= 2:
                return float('inf')
            endpoints = self._river_endpoints_local(river_side)
            if any(self._hex_has_enemy_unit_for_fleet(h, unit) for h in endpoints):
                return float('inf')
            return 1

        # 3. Standard Sea/Coastal/Maelstrom Movement
        terrain = self.get_terrain(to_hex)
        valid_sea_terrains = [
            TerrainType.OCEAN,
            TerrainType.MAELSTROM
        ]
        if terrain in valid_sea_terrains or self.is_coastal(to_hex):
            return 1

        return float('inf')


    def displace_enemy_fleets(self, army, target_hex):
        """
        Rule: Army entering hex moves enemy ships to nearest safe hex.
        """
        units_in_hex = self.get_units_in_hex(target_hex.q, target_hex.r)[:]

        for u in units_in_hex:
            if u.unit_type == UnitType.FLEET and self.are_enemies(army, u):
                retreat_state = self._find_nearest_safe_fleet_state(u, target_hex, army.allegiance)
                if retreat_state:
                    retreat_hex, retreat_side = retreat_state
                    self.move_unit_internal(u, retreat_hex)
                    u.river_hexside = retreat_side
                else:
                    u.destroy() # No escape, ship destroyed

    def _find_nearest_safe_fleet_state(self, fleet, start_hex, enemy_allegiance):
        start_state = (start_hex, getattr(fleet, "river_hexside", None))
        start_key = self._fleet_state_key(start_state)
        frontier = []
        heapq.heappush(frontier, (0, 0, start_state))
        cost_so_far = {start_key: 0}
        counter = 1

        while frontier:
            current_cost, _, state = heapq.heappop(frontier)
            state_key = self._fleet_state_key(state)
            if current_cost > cost_so_far.get(state_key, float("inf")):
                continue

            current_hex, _ = state
            if state_key != start_key:
                units = self.get_units_in_hex(current_hex.q, current_hex.r)
                has_enemy_army = any(
                    getattr(u, "is_army", lambda: False)() and u.allegiance == enemy_allegiance
                    for u in units
                )
                if not has_enemy_army:
                    return state

            for next_state, step_cost in self._fleet_neighbor_states(fleet, state):
                next_key = self._fleet_state_key(next_state)
                new_cost = current_cost + step_cost
                if new_cost < cost_so_far.get(next_key, float("inf")):
                    cost_so_far[next_key] = new_cost
                    heapq.heappush(frontier, (new_cost, counter, next_state))
                    counter += 1

        return None

    def _find_nearest_safe_sea_hex(self, fleet, current_hex, enemy_allegiance):
        """BFS to find nearest hex that is water/coastal and free of enemy armies."""
        queue = [(current_hex, 0)]
        visited = {current_hex}

        while queue:
            curr, dist = queue.pop(0)

            # Check if this hex is valid destination (excluding the one we are being kicked out of)
            if curr != current_hex:
                # Must be water/coastal
                is_valid_terrain = (self.get_terrain(curr) == TerrainType.OCEAN or
                                    self.is_coastal(curr) or
                                    self._hexside_is(self.get_effective_hexside(current_hex, curr), HexsideType.DEEP_RIVER)) # Simplified river check

                if is_valid_terrain:
                    # Check for enemy armies
                    units = self.get_units_in_hex(curr.q, curr.r)
                    has_enemy_army = any(
                        u.is_army() and u.allegiance == enemy_allegiance
                        for u in units
                    )

                    if not has_enemy_army:
                        return curr

            # Add neighbors
            for neighbor in curr.neighbors():
                if neighbor not in visited and self.is_valid_hex(neighbor):
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))

        return None

    def move_unit_internal(self, unit, new_hex):
        """Helper to update unit position and internal unit map."""
        # Remove from old
        if unit.position:
            old_q, old_r = unit.position
            if (old_q, old_r) in self.unit_map:
                if unit in self.unit_map[(old_q, old_r)]:
                    self.unit_map[(old_q, old_r)].remove(unit)

        # Update unit
        unit.position = (new_hex.q, new_hex.r)

        # Add to new
        if (new_hex.q, new_hex.r) not in self.unit_map:
            self.unit_map[(new_hex.q, new_hex.r)] = []
        self.unit_map[(new_hex.q, new_hex.r)].append(unit)

    def are_enemies(self, unit_a, unit_b):
        """Simple allegiance check."""
        return unit_a.allegiance != unit_b.allegiance

    def is_maelstrom(self, hex_obj):
        """Checks if the hex is part of the Maelstrom region."""
        # Maelstrom is a specific terrain type in the CSV (e.g. 'maelstrom')
        return self.get_terrain(hex_obj) == TerrainType.MAELSTROM

    def get_maelstrom_exits(self, hex_obj):
        """
        Returns a list of valid exit hexes (axial) for a ship emerging from the Maelstrom.
        Valid exits are adjacent hexes that are NOT Maelstrom and are sea/coastal.
        """
        exits = []
        for neighbor in hex_obj.neighbors():
            # Must not be Maelstrom itself (we want to leave it)
            if self.is_maelstrom(neighbor):
                continue

            # Must be valid water terrain (Ocean or Coastal)
            # Checking is_coastal handles 'c_...' terrains, get_terrain returns stripped
            t_type = self.get_terrain(neighbor)
            if t_type == TerrainType.OCEAN or self.is_coastal(neighbor):
                exits.append(neighbor)

        return exits

    def _get_ground_movement_cost(self, unit, from_hex, to_hex):
        """Rule 5: Moving Ground troops. Restrictions and Hexside Barriers"""

        terrain = self.get_terrain(to_hex)
        hexside_type = self.get_effective_hexside(from_hex, to_hex)

        # Rule 5: Ground Army Restrictions
        forbidden_terrain = [
            TerrainType.OCEAN,
            TerrainType.DESERT,
            TerrainType.SWAMP,
            TerrainType.MAELSTROM
        ]
        if terrain in forbidden_terrain:
            return float('inf')

        # Calculate Costs
        cost = 1

        # Mountains are impassable, unless there is a pass
        if terrain == TerrainType.MOUNTAIN:
            if not self._hexside_is(hexside_type, HexsideType.PASS):
                return float('inf')
            else:
                cost += 1

        # Forest costs 2, unless unit has Forest affinity (Elves/Kender)
        if terrain == TerrainType.FOREST:
            if unit.terrain_affinity == TerrainType.FOREST:
                pass
            else:
                cost += 1

        # Rule 5: Hexside Barriers
        if self._hexside_is(hexside_type, HexsideType.SEA) or self._hexside_is(hexside_type, HexsideType.DEEP_RIVER):
            return float('inf')

        if self._hexside_is(hexside_type, HexsideType.RIVER):
            cost += 2

        if self._hexside_is(hexside_type, HexsideType.MOUNTAIN):
            # Affinity override: Dwarves/Ogres often have 'mountain' affinity in CSV
            if unit.terrain_affinity == TerrainType.MOUNTAIN:
                cost += 1
            else:
                return float('inf')

        return cost

    def get_neighbors(self, hex_coord, unit):
        """
        Returns accessible neighbors considering Rule 5 and Sea Barriers.
        """
        neighbors = []
        currently_in_zoc = self.is_adjacent_to_enemy(hex_coord, unit)
        zoc_restricted = bool(unit.is_army() and unit.unit_type != UnitType.CAVALRY)

        for neighbor in hex_coord.neighbors():
            # 1. Basic Bounds Check
            col, row = neighbor.axial_to_offset()
            if not (0 <= col < self.width and 0 <= row < self.height):
                continue

            # 2. Check for Sea Barriers (Rule 5)
            # If ground unit, check if the hexside between current and neighbor is 'sea'
            if unit.unit_type != UnitType.WING:
                hexside = self.get_effective_hexside(hex_coord, neighbor)
                if self._hexside_is(hexside, HexsideType.SEA):  # Explicitly mark water-only boundaries in config
                    continue

            # 3. Cannot occupy enemy hex
            if self.has_enemy_army(neighbor, unit.allegiance):
                continue

            # Rule 5: Movement must stop if moving from ZOC to another ZOC hex
            if currently_in_zoc and zoc_restricted:
                if self.is_adjacent_to_enemy(neighbor, unit):
                    continue

            neighbors.append(neighbor)
        return neighbors

    def find_shortest_path(self, unit, start_hex, target_hex):
        """
        Calculates the shortest path using A* algorithm.
        Returns a list of hex coordinates.
        """
        max_mp = getattr(unit, "movement_points", unit.movement)
        frontier = []
        heapq.heappush(frontier, (0, start_hex))
        came_from = {start_hex: None}
        cost_so_far = {start_hex: 0}

        while frontier:
            current = heapq.heappop(frontier)[1]
            if current == target_hex: break

            for neighbor in self.get_neighbors(current, unit):
                cost = self.get_movement_cost(unit, current, neighbor)
                new_cost = cost_so_far[current] + cost
                
                if new_cost <= max_mp:
                    if neighbor not in cost_so_far or new_cost < cost_so_far[neighbor]:
                        cost_so_far[neighbor] = new_cost
                        priority = new_cost + self.heuristic(target_hex, neighbor)
                        heapq.heappush(frontier, (priority, neighbor))
                        came_from[neighbor] = current

        return self.reconstruct_path(came_from, start_hex, target_hex)

    def heuristic(self, a, b):
        """Hexagonal distance heuristic for A*."""
        return (abs(a.q - b.q) + abs(a.q + a.r - b.q - b.r) + abs(a.r - b.r)) / 2

    def reconstruct_path(self, came_from, start, goal):
        current = goal
        path = []
        while current != start:
            if current not in came_from: return [] # No path found
            path.append(current)
            current = came_from[current]
        path.reverse()
        return path

    def get_reachable_hexes(self, units):
        """
        Calculates all reachable hexes for a stack of units.
        Returns a list of Hex objects.
        """
        if not units:
            return []
        if len(units) == 1 and units[0].unit_type == UnitType.FLEET:
            return self.get_reachable_hexes_for_fleet(units[0])

        # 1. Determine Stack Constraints
        start_hex = None
        min_mp = 999

        for unit in units:
            if not getattr(unit, 'is_on_map', True):
                continue
            if hasattr(unit, 'position') and unit.position:
                col, row = unit.position
                # Assuming unit.position is (col, row)
                h = Hex.offset_to_axial(col, row)
                if start_hex is None:
                    start_hex = h
                elif start_hex != h:
                    # Units in different locations cannot move as a stack
                    return []

            m = getattr(unit, "movement_points", unit.movement)
            min_mp = min(min_mp, m)

        if not start_hex or min_mp <= 0:
            return []

        frontier = []
        heapq.heappush(frontier, (0, start_hex))
        cost_so_far = {start_hex: 0}

        reachable_hexes = []

        while frontier:
            current_cost, current_hex = heapq.heappop(frontier)

            if current_cost > min_mp:
                continue

            # Optimization check
            if current_cost > cost_so_far.get(current_hex, float('inf')):
                continue

            # VALID DESTINATION CHECK
            # We can only stop (highlight) this hex if stacking limits allow it.
            if current_hex != start_hex:
                if self.can_stack_move_to(units, current_hex) and all(
                    self.can_unit_land_on_hex(u, current_hex) for u in units
                ):
                    reachable_hexes.append(current_hex)

            # Explore neighbors using stack movement rules
            for next_hex in current_hex.neighbors():
                # 1. Bounds check
                c, r = next_hex.axial_to_offset()
                if not (0 <= c < self.width and 0 <= r < self.height):
                    continue

                stack_cost = 0
                possible = True

                for unit in units:
                    # Check 1: Is hex occupied by enemy?
                    if self.has_enemy_army(next_hex, unit.allegiance):
                        possible = False
                        break

                    # Check 2: Sea Barrier (if not handled by cost)
                    # Note: get_movement_cost usually returns inf for ground vs sea,
                    # but explicit hexside check mimics get_neighbors behavior.
                    if unit.unit_type != UnitType.WING:
                        hexside = self.get_effective_hexside(current_hex, next_hex)
                        if self._hexside_is(hexside, HexsideType.SEA):
                            possible = False
                            break

                    # Check 3: ZOC (Rule 5) applies only to non-cavalry Army units.
                    zoc_restricted = bool(unit.is_army() and unit.unit_type != UnitType.CAVALRY)
                    if zoc_restricted:
                        if self.is_adjacent_to_enemy(current_hex, unit) and self.is_adjacent_to_enemy(next_hex, unit):
                            possible = False
                            break

                    # Check 4: Movement Cost
                    cost = self.get_movement_cost(unit, current_hex, next_hex)
                    if cost == float('inf') or cost is None:
                        possible = False
                        break

                    stack_cost = max(stack_cost, cost)

                if not possible:
                    continue

                new_cost = current_cost + stack_cost
                if new_cost <= min_mp:
                    if next_hex not in cost_so_far or new_cost < cost_so_far[next_hex]:
                        cost_so_far[next_hex] = new_cost
                        heapq.heappush(frontier, (new_cost, next_hex))

        return reachable_hexes
