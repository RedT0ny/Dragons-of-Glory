import heapq
from collections import defaultdict
from src.content.specs import HexDirection, UnitType, UnitRace, GamePhase, LocType, TerrainType


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
        if side_type == "deep_river":
            self.navigable_edges.add(key)

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
            return

        col, row = unit.position

        # Fix: Ensure position coordinates are valid integers before converting
        if col is None or row is None:
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
                if u.unit_type == "fleet" and u.allegiance == alliance:
                    # Check if this ship is stationed on THIS specific hexside
                    if getattr(u, 'river_hexside', None) == key:
                        # Optional: Add check for 'has_moved_this_turn' if you track that
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

    def has_enemy_army(self, hex_coord, alliance):
        """Rule 5: Check if hex contains any army from a different alliance."""
        units = self.get_units_in_hex(hex_coord.q, hex_coord.r)
        for u in units:
            if u.allegiance != alliance and u.allegiance != 'neutral':
                return True
        return False

    def is_adjacent_to_enemy(self, hex_coord, unit):
        """Rule 5: Check ZOC proximity, respecting terrain barriers."""
        for neighbor in hex_coord.neighbors():
            if self.has_enemy_army(neighbor, unit.allegiance):
                hexside = self.get_hexside(hex_coord, neighbor)
                # "Armies are never considered adjacent if separated by mountain or deep river"
                if hexside not in ["mountain", "deep_river"]:
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
        if terrain == "desert": return float('inf')  # Cannot enter desert

        cost = 1
        # It costs one extra Movement Point for an air army to fly over a mountain hexside.
        if self.get_hexside(from_hex, to_hex) == "mountain":
            cost += 1
        return cost

    def _get_fleet_movement_cost(self, unit, from_hex, to_hex):
        """
        Rule 4: Ships count hexsides moved along (deep rivers).
        Also checks for enemy ships/armies (Blocking) and Stacking.
        """
        # 1. Check for Blocking Enemies
        # "A ship cannot enter a hex... containing an enemy ship... or enemy army."
        target_units = self.get_units_in_hex(to_hex.q, to_hex.r)
        for u in target_units:
            if self.are_enemies(unit, u):
                if u.unit_type == UnitType.FLEET:
                    return float('inf') # Blocked by enemy ship
                if u.is_army():
                    return float('inf') # Blocked by enemy army

        # 2. Check River Movement & Stacking
        # "Only two ships may be stacked in a river hexside."
        if self.get_hexside(from_hex, to_hex) == "deep_river":
            # Count friendly fleets currently in destination that are also 'in river'
            # Assuming 'river_hexside' property indicates if they are in a river state
            fleets_in_river = [
                u for u in target_units
                if u.unit_type == UnitType.FLEET and u.river_hexside is not None
            ]
            if len(fleets_in_river) >= 2:
                return float('inf') # Stacking limit reached
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
                # Find retreat location
                retreat_hex = self._find_nearest_safe_sea_hex(u, target_hex, army.allegiance)

                if retreat_hex:
                    self.move_unit_internal(u, retreat_hex)
                    # Reset river status if forced out to sea
                    if self.get_terrain(retreat_hex) == "ocean":
                        u.river_hexside = None
                else:
                    u.destroy() # No escape, ship destroyed

    def _find_nearest_safe_sea_hex(self, fleet, current_hex, enemy_allegiance):
        """BFS to find nearest hex that is water/coastal and free of enemy armies."""
        queue = [(current_hex, 0)]
        visited = {current_hex}

        while queue:
            curr, dist = queue.pop(0)

            # Check if this hex is valid destination (excluding the one we are being kicked out of)
            if curr != current_hex:
                # Must be water/coastal
                is_valid_terrain = (self.get_terrain(curr) == "ocean" or
                                    self.is_coastal(curr) or
                                    self.get_hexside(current_hex, curr) == "deep_river") # Simplified river check

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

    def is_valid_fleet_deployment(self, hex_obj: Hex, country, phase):
        """
        Deployment: Any coastal hex.
        Replacements: Only ports.
        """
        hex_coords = hex_obj.axial_to_offset()

        # 1. Must be in country
        if not country.is_hex_in_country(*hex_coords):
            return False

        # 2. Check Phase logic
        if phase == GamePhase.DEPLOYMENT:
            # Ports are also valid deployment hexes
            if self.is_coastal(hex_obj):
                return True
            for loc in country.locations.values():
                if loc.coords == hex_coords and loc.loc_type == LocType.PORT.value:
                    return True
            return False
        elif phase == GamePhase.REPLACEMENTS:
            # Check if hex has a port
            # We iterate country locations to find if one is at this hex and is a PORT
            for loc in country.locations.values():
                if loc.coords == hex_coords and loc.loc_type == LocType.PORT.value:
                    return True
            return False

        return False

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
        hexside_type = self.get_hexside(from_hex, to_hex)

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
            if hexside_type != "pass":
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
        if hexside_type in ["sea","deep_river"]:
            return float('inf')

        if hexside_type == "river":
            cost += 2

        if hexside_type == "mountain":
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
        is_exempt = unit.unit_type in [UnitType.CAVALRY, UnitType.WING] or unit.is_leader()

        for neighbor in hex_coord.neighbors():
            # 1. Basic Bounds Check
            col, row = neighbor.axial_to_offset()
            if not (0 <= col < self.width and 0 <= row < self.height):
                continue

            # 2. Check for Sea Barriers (Rule 5)
            # If ground unit, check if the hexside between current and neighbor is 'sea'
            if unit.unit_type != UnitType.WING:
                hexside = self.get_hexside(hex_coord, neighbor)
                if hexside == "sea":  # Explicitly mark water-only boundaries in config
                    continue

            # 3. Cannot occupy enemy hex
            if self.has_enemy_army(neighbor, unit.allegiance):
                continue

            # Rule 5: Movement must stop if moving from ZOC to another ZOC hex
            if currently_in_zoc and not is_exempt:
                if self.is_adjacent_to_enemy(neighbor, unit):
                    continue

            neighbors.append(neighbor)
        return neighbors

    def find_shortest_path(self, unit, start_hex, target_hex):
        """
        Calculates the shortest path using A* algorithm.
        Returns a list of hex coordinates.
        """
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
                
                if new_cost <= unit.movement:
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

            m = unit.movement
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
                if self.can_stack_move_to(units, current_hex):
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
                    if unit.unit_type != 'wing':
                        hexside = self.get_hexside(current_hex, next_hex)
                        if hexside == "sea":
                            possible = False
                            break

                    # Check 3: ZOC (Rule 5)
                    # If currently in ZOC, cannot move to another ZOC hex.
                    # Exemptions: Cavalry, Wing, Leader (UnitType check or method)
                    is_exempt = unit.unit_type in ['cavalry', 'wing'] or (hasattr(unit, 'is_leader') and unit.is_leader())
                    if not is_exempt:
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