class Country:
    def __init__(self, name, color, is_ai=False):
        self.name = name
        self.color = color  # For map rendering
        self.is_ai = is_ai
        self.units = []
        self.territories = []

    def add_unit(self, unit):
        self.units.append(unit)

    def add_territory(self, hex_tile):
        self.territories.append(hex_tile)

    def __repr__(self):
        return f"<Country {self.name} (AI: {self.is_ai})>"
