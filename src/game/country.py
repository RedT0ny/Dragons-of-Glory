class Location:
    """
    Represents a strategic point on the map.
    Example: Location('solace', 'city', (12, 15), name='Solace')
    """
    def __init__(self, loc_id, loc_type, coords, loc_name=None):
        self.id = loc_id
        self.loc_type = loc_type  # 'city' or 'fortress'
        self.coords = coords      # (col, row) offset coordinates
        self.name = loc_name
        self.occupier = None      # 'highlord', 'whitestone', or None
        self.is_capital = False

    def get_defense_modifier(self):
        """
        Returns the combat rating bonus provided by the location.
        As per Dragon #107 Advanced Rules.
        """
        return 2 if self.loc_type == 'fortress' else 1

    def __repr__(self):
        prefix = "Capital " if self.is_capital else ""
        return f"<{prefix}{self.loc_type.title()} {self.id} at {self.coords}>"

class Country:
    def __init__(self, country_id, capital_id, strength, allegiance='neutral', alignment=(0, 0), color=None):
        self.id = country_id
        self.capital_id = capital_id  # The ID of the location currently serving as capital
        self.strength = strength      # Base political/economic strength
        self.allegiance = allegiance  # 'whitestone', 'highlord', or 'neutral'
        
        # alignment: Tuple (WS, HL) representing activation modifiers.
        # Positive values make it easier for that side to convince the country.
        self.alignment = alignment    
        
        self.color = color
        self.units = []
        self.territories = set()      # Collection of hex coordinates (col, row)
        self.locations = {}           # Dict of {loc_id: Location object}

    def get_name(self, translator):
        return translator.get_country_name(self.id)

    def set_territories(self, coord_list):
        """
        Accepts a list of [col, row] lists from YAML
        and converts them to a set of tuples for fast lookup.
        """
        self.territories = {tuple(c) for c in coord_list}

    def is_hex_in_country(self, col, row):
        """Quick check if a map hex belongs to this country's borders."""
        return (col, row) in self.territories

    @property
    def capital(self):
        """Helper to access the current capital Location object."""
        return self.locations.get(self.capital_id)

    def get_capital_name(self, translator):
        """Returns the translated name of the current capital city."""
        return translator.get_capital_name(self.capital_id)

    def add_location(self, location: Location):
        """Registers a city or fortress and tags it if it's the capital."""
        self.locations[location.id] = location
        if location.id == self.capital_id:
            location.is_capital = True

    def set_capital(self, location_id):
        """Moves the capital status to a different existing location (e.g. Silvanesti)."""
        if location_id in self.locations:
            if self.capital:
                self.capital.is_capital = False
            self.capital_id = location_id
            self.locations[location_id].is_capital = True

    def add_unit(self, unit):
        """Links a unit to this country's management."""
        unit.land = self.id
        unit.allegiance = self.allegiance
        self.units.append(unit)

    @property
    def total_military_strength(self):
        """Calculates current CR of all active/alive units."""
        return sum(u.combat_rating for u in self.units if u.is_alive())

    def change_allegiance(self, new_allegiance):
        """Flips country and all its units to a new side (Rule DL11 Activation)."""
        self.allegiance = new_allegiance
        for unit in self.units:
            unit.allegiance = new_allegiance

    def is_conquered(self):
        """Victory Check: Conquered if ALL locations are held by the enemy side."""
        enemy = 'highlord' if self.allegiance == 'whitestone' else 'whitestone'
        if not self.locations: 
            return False
        return all(loc.occupier == enemy for loc in self.locations.values())

    def surrender(self):
        """Deactivates all units upon total conquest."""
        for unit in self.units:
            unit.status = "inactive"

    def __repr__(self):
        return f"<Country {self.id} [{self.allegiance}] - Capital: {self.capital_id}>"
