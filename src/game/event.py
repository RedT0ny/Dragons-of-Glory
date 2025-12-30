class Event:
    def __init__(self, name, description, trigger, effect):
        self.name = name
        self.description = description
        self.trigger = trigger
        self.effect = effect
        self.is_active = True

    def check_trigger(self, game_state):
        return self.is_active and self.trigger(game_state)

    def activate(self, game_state):
        if self.check_trigger(game_state):
            if callable(self.effect):
                self.effect(game_state)
            elif isinstance(self.effect, list):
                for e in self.effect:
                    e(game_state)
            self.deactivate()

    def deactivate(self):
        self.is_active = False

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
