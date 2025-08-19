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
