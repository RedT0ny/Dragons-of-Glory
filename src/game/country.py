class Country:
    def __init__(self, name, capital, allegiance, alignment=(0, 0), color=None, is_ai=False):
        self.name = name
        self.capital = capital
        self.allegiance = allegiance  # 'Whitestone', 'Highlord', or 'Neutral'
        self.alignment = alignment    # Activation Bonus/malus (WS, HL)
        self.color = color
        self.is_ai = is_ai
        
        self.units = []
        self.territories = []

    def add_unit(self, unit):
        """Assigns a unit to this country and updates the unit's origin."""
        unit.land = self.name
        unit.allegiance = self.allegiance
        self.units.append(unit)

    @property
    def total_military_strength(self):
        """Calculates the total CR of all alive units in the country."""
        return sum(u.combat_rating for u in self.units if u.is_alive())

    def change_allegiance(self, new_allegiance):
        """Rule DL11: When a neutral country is invaded or convinced."""
        self.allegiance = new_allegiance
        for unit in self.units:
            unit.allegiance = new_allegiance

    def set_boundaries(self, territories):
        """Sets the territories controlled by this country."""
        self.territories = territories


    def surrender(self):
        """Handles the surrender of the country by clearing its units."""
        self.units = [] # It should actually get the country units and mark them as 'inactive'.

    def __repr__(self):
        return f"<Country {self.name} [{self.allegiance}] - Strength: {self.total_military_strength}>"
