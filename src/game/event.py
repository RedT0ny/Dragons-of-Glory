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
    def __init__(self, name, description, bonus, requirements=None, is_consumable=False):
        self.name = name
        self.description = description
        self.bonus = bonus # Can be int or a function
        self.requirements = requirements or [] # e.g. ["solamnic"] or ["has_silver_arm"]
        self.is_consumable = is_consumable
        self.owner = None

    def can_equip(self, unit):
        # Check race requirements
        if "solamnic" in self.requirements and unit.race != "solamnic":
            return False
        # Add logic for specific artifact dependencies here
        return True

    def apply_to(self, unit):
        if self.can_equip(unit):
            unit.equipment.append(self)
            self.owner = unit

    def remove_from(self, unit):
        if isinstance(self.bonus, dict):
            for stat, value in self.bonus.items():
                setattr(unit, stat, getattr(unit, stat, 0) - value)
        self.owner = None

    def use(self, game_state):
        if self.is_consumable and callable(self.bonus):
            self.bonus(game_state)
            self.owner = None
