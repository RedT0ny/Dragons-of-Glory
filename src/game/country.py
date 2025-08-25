class Country:
    def __init__(self, name, color, capital, allegiance, activation, is_ai=False):
        self.name = name
        self.color = color  # For map rendering
        self.capital = capital
        self.allegiance = allegiance # Whitesone, Highlord, neutral
        #self.alignment = (none,none) # (WS, HL) activation bonus/malus only for basic rules
        self.activation = activation # Activation bonus for the country
        self.is_ai = is_ai
        self.units = []
        self.territories = []

    def add_unit(self, unit):
        self.units.append(unit)

    def add_territory(self, hex_tile):
        self.territories.append(hex_tile)

    def __repr__(self):
        return f"<Country {self.name} (AI: {self.is_ai})>"
