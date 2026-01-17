import heapq
from src.content.specs import HexDirection

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
        """
        # Mapping our Enum to logical coordinate offsets
        lookup = {
            HexDirection.EAST:       Hex(1, 0),
            HexDirection.NORTH_EAST: Hex(1, -1),
            HexDirection.NORTH_WEST: Hex(0, -1),
            HexDirection.WEST:       Hex(-1, 0),
            HexDirection.SOUTH_WEST: Hex(-1, 1),
            HexDirection.SOUTH_EAST: Hex(0, 1)
        }
        return [self + offset for offset in lookup.values()]

    def distance_to(self, other):
        """Cálculo de distancia Manhattan para hexágonos."""
        return (abs(self.q - other.q) + 
                abs(self.q + self.r - other.q - other.r) + 
                abs(self.r - other.r)) // 2

    def __repr__(self):
        col, row = self.axial_to_offset()
        return f"Hex(Axial:{self.q},{self.r} | Offset:{col:02d}{row:02d})"

    def __eq__(self, other):
        return self.q == other.q and self.r == other.r

    def __hash__(self):
        return hash((self.q, self.r))


class HexGrid:
    """
    Manage the collection of hexagons and the relationship with the units.
    """
    def __init__(self, width, height, offset_q=0, offset_r=0):
        self.width = width
        self.height = height
        # offset_q and offset_r represent the 'origin' of this scenario 
        # on the master Ansalon map.
        self.offset_q = offset_q
        self.offset_r = offset_r
        
        self.grid = {}  # (q, r) -> terrain_type
        self.hexside_data = {}  # ((q1,r1), (q2,r2)) -> border_type
        # Add a way to quickly find which hexsides are rivers
        self.navigable_edges = set()
        self.unit_map = {}
        self.special_hexes = {} # (q, r) -> "fortified_city", etc.

    def load_from_csv(self, terrain_csv_path):
        """Loads terrain data from a CSV grid."""
        import csv
        with open(terrain_csv_path, mode='r') as f:
            reader = csv.reader(f)
            header = next(reader) # Skip column headers
            for row_idx, row in enumerate(reader):
                for col_idx, terrain in enumerate(row[1:]): # skip row header
                    hex_obj = Hex.offset_to_axial(col_idx, row_idx)
                    self.grid[(hex_obj.q, hex_obj.r)] = terrain

    def add_hexside(self, q1, r1, q2, r2, side_type):
        """Registers a special border between two hexes (River/Mountain)."""
        key = tuple(sorted([(q1, r1), (q2, r2)]))
        self.hexside_data[key] = side_type

        # Rule 4: Ships can only move along Deep Rivers.
        # Fords and Bridges are for ground units and usually block large ships.
        if side_type == "deep_river":
            self.navigable_edges.add(key)

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
        """Converts local scenario coordinates to master map coordinates."""
        return q + self.offset_q, r + self.offset_r

    def get_terrain(self, hex_coord):
        master_q, master_r = self.to_master_coords(hex_coord.q, hex_coord.r)
        raw_terrain = self.grid.get((master_q, master_r), "plain")
        
        # If it starts with 'c_', it's coastal. Return the part after 'c_'.
        if raw_terrain.startswith("c_"):
            return raw_terrain[2:]
        return raw_terrain

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

    def get_units_in_hex(self, q, r):
        return self.unit_map.get((q, r), [])

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
        if unit.unit_type == "wizard":
            return 0  # Rule 5: Wizards ignore hex costs

        if unit.unit_type == "wing":
            return self._get_wing_movement_cost(unit, from_hex, to_hex)
        if unit.unit_type == "fleet":
            return self._get_fleet_movement_cost(from_hex, to_hex)

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

    def _get_fleet_movement_cost(self, from_hex, to_hex):
        """Rule 4: Ships count hexsides moved along (deep rivers)."""
        if self.get_hexside(from_hex, to_hex) == "deep_river":
            return 1
        # Ships move normally in Sea/Coastal hexes
        if self.get_terrain(to_hex) == "ocean" or self.is_coastal(to_hex):
            return 1
        return float('inf')

    def _get_ground_movement_cost(self, unit, from_hex, to_hex):
        """Rule 5: Moving Ground troops. Restrictions and Hexside Barriers"""

        terrain = self.get_terrain(to_hex)
        hexside_type = self.get_hexside(from_hex, to_hex)

        # Rule 5: Ground Army Restrictions
        if terrain in ["sea", "desert", "marsh"]:
            return float('inf')

        # Calculate Costs
        cost = 1

        # Mountains are impassable, unless there is a pass
        if terrain == "mountain":
            if hexside_type != "pass":
                return float('inf')
            else:
                cost += 1

        # Forest costs 2, unless unit has Forest affinity (Elves/Kender)
        if terrain == "forest":
            if unit.terrain_affinity == "forest":
                pass
            else:
                cost += 1

        # Rule 5: Hexside Barriers
        if hexside_type == "river":
            cost += 2

        if hexside_type == "mountain":
            # Affinity override: Dwarves/Ogres often have 'mountain' affinity in CSV
            if unit.terrain_affinity in ["mountain","all"]:
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
        is_exempt = unit.unit_type in ['cavalry', 'wing'] or unit.is_leader()

        for neighbor in hex_coord.neighbors():
            # 1. Basic Bounds Check
            col, row = neighbor.axial_to_offset()
            if not (0 <= col < self.width and 0 <= row < self.height):
                continue

            # 2. Check for Sea Barriers (Rule 5)
            # If ground unit, check if the hexside between current and neighbor is 'sea'
            if unit.unit_type != 'wing':
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
