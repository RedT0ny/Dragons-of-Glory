import heapq

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
        """Returns the 6 neighboring hexagons."""
        directions = [
            Hex(1, 0), Hex(1, -1), Hex(0, -1),
            Hex(-1, 0), Hex(-1, 1), Hex(0, 1)
        ]
        return [self + d for d in directions]

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
        
        self.grid = {} # Shared master terrain data
        self.hexside_data = {} # Shared master hexside data
        self.unit_map = {} 

    def to_master_coords(self, q, r):
        """Converts local scenario coordinates to master map coordinates."""
        return q + self.offset_q, r + self.offset_r

    def get_terrain(self, hex_coord):
        master_q, master_r = self.to_master_coords(hex_coord.q, hex_coord.r)
        return self.grid.get((master_q, master_r), "plain")

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
        Rule 5 & 6: Data-driven movement costs using terrain_affinity.
        """
        # Rule 5: Wizards and Leaders move anywhere (cost 0 for pathfinding)
        if unit.is_leader():
            return 0

        terrain = self.get_terrain(to_hex)
        hexside_type = self.get_hexside(from_hex, to_hex)
        
        # Rule 6: Flying Creatures (Wing)
        if unit.unit_type == "wing":
            if terrain == "desert": return float('inf')
            cost = 1
            if hexside_type == "mountain": cost += 1
            return cost

        # Rule 5: Ground Army Restrictions
        if terrain in ["sea", "desert", "marsh"]:
            return float('inf')

        # Rule 5: Hexside Barriers
        if hexside_type in ["mountain", "deep_river"]:
            # Affinity override: Dwarves/Ogres often have 'mountain' affinity in CSV
            if hexside_type == "mountain" and unit.terrain_affinity == "mountain":
                pass 
            else:
                return float('inf')

        # Calculate Costs
        cost = 1
        
        # Forest costs 2, unless unit has Forest affinity (Elves/Kender)
        if terrain == "forest":
            cost = 1 if unit.terrain_affinity == "forest" else 2

        # Hexside Penalties
        if hexside_type == "river":
            cost += 2
        elif hexside_type == "mountain":
            cost += 1 # Affinity users pay 1 extra to cross the barrier

        return cost

    def get_neighbors(self, hex_coord, unit):
        """
        Returns accessible neighbors considering Rule 5 Zone of Control.
        """
        neighbors = []
            
            # Rule 5: If ground army starts adjacent to enemy, can only move if 
            # first move puts it in a hex NOT adjacent to an enemy. (Cavalry/Flyers exempt)
        currently_in_zoc = self.is_adjacent_to_enemy(hex_coord, unit)
        # Cavalry and Leaders are exempt from ZOC-to-ZOC restrictions
        is_exempt = unit.unit_type == 'cavalry' or unit.is_leader() or unit.unit_type == 'wing'

        for neighbor in hex_coord.neighbors():
            # Basic Bounds
            col, row = neighbor.axial_to_offset()
            if not (0 <= col < self.width and 0 <= row < self.height):
                continue

            # Rule 5: Cannot occupy enemy hex
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
