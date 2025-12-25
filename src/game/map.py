class Hex:
    """
    Represents a hexagon using axial coordinates (q, r).
    Includes methods for offset conversion and mathematical calculations.
    """
    def __init__(self, q, r):
        self.q = q
        self.r = r

    @property
    def s(self):
        """Implicit cube coordinate: q + r + s = 0"""
        return -self.q - self.r

    def to_offset(self):
        """Converts axial (q, r) to offset (col, row) for the rectangular map."""
        # Asumiendo 'pointy top' y 'odd-r' (común en mapas rectangulares)
        col = self.q + (self.r - (self.r & 1)) // 2
        row = self.r
        return col, row

    @staticmethod
    def from_offset(col, row):
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
        col, row = self.to_offset()
        return f"Hex(Axial:{self.q},{self.r} | Offset:{col:02d}{row:02d})"

    def __eq__(self, other):
        return self.q == other.q and self.r == other.r

    def __hash__(self):
        return hash((self.q, self.r))

class HexGrid:
    """
    Manage the collection of hexagons and the relationship with the units.
    """
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.tiles = {}  # {(q, r): HexTile}
        self.unit_map = {}  # {(q, r): [Unit, ...]}

    def get_units_in_hex(self, q, r):
        """Returns the list of units at a specific coordinate."""
        return self.unit_map.get((q, r), [])

    def get_nearby_units(self, hex_center, radius=1):
        """
        Searches for units in neighboring hexagons.
        Useful for intercepts and control zones.
        """
        nearby = []
        # Para radio 1, solo vecinos directos
        target_hexes = [hex_center]
        if radius >= 1:
            target_hexes.extend(hex_center.neighbors())
        
        # Expand to larger radii if necessary (dragon fire, etc)
        # ... ring_logic ...

        for h in target_hexes:
            nearby.extend(self.get_units_in_hex(h.q, h.r))
        return nearby

    def move_unit(self, unit, target_hex):
        """Updates the unit's position in the map and the unit list."""
        old_pos = unit.position # We assume that unit.position is a Hex object or (q,r)
        if old_pos in self.unit_map:
            self.unit_map[old_pos].remove(unit)
        
        new_pos = (target_hex.q, target_hex.r)
        if new_pos not in self.unit_map:
            self.unit_map[new_pos] = []
        self.unit_map[new_pos].append(unit)
        unit.position = new_pos
