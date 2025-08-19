class Artifact:
    def __init__(self, name, description, bonus, is_consumable=False):
        self.name = name
        self.description = description
        self.bonus = bonus
        self.owner = None
        self.is_consumable = is_consumable

    def apply_to(self, unit):
        self.owner = unit
        if isinstance(self.bonus, dict):
            for stat, value in self.bonus.items():
                setattr(unit, stat, getattr(unit, stat, 0) + value)
        elif callable(self.bonus):
            self.bonus(unit)

    def remove_from(self, unit):
        if isinstance(self.bonus, dict):
            for stat, value in self.bonus.items():
                setattr(unit, stat, getattr(unit, stat, 0) - value)
        self.owner = None

    def use(self, game_state):
        if self.is_consumable and callable(self.bonus):
            self.bonus(game_state)
            self.owner = None
