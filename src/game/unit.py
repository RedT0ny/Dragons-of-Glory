class Unit:
    """
    Base class for all units in the game.

    :ivar name: The name of the unit.
    :type name: str
    :ivar unit_type: The type of the unit (e.g., 'hero', 'leader', 'fleet', 'army').
    :type unit_type: str
    :ivar country: The country the unit belongs to.
    :type country: Any
    :ivar position: The current position of the unit on the map (e.g., hex coordinates).
    :type position: Any
    :ivar health: The current health of the unit.
    :type health: int
    :ivar status: The current status of the unit (e.g., 'active', 'defeated').
    :type status: str
    """
    def __init__(self, name, unit_type, country, position, health=100, status='active'):
        self.name = name
        self.unit_type = unit_type
        self.allegiance = allegiance  # Whitesone, Highlord, neutral
        self.country = country
        self.color = color  # Color for the unit, e.g., 'red', 'blue'
        self.movement = movement  # Movement points for the unit
        self.position = position
        self.health = health
        self.status = status

    def move(self, new_position):
        self.position = new_position

    def take_damage(self, amount):
        self.health -= amount
        if self.health <= 0:
            self.status = 'defeated'

    def is_alive(self):
        return self.health > 0 and self.status == 'active'

class Leader(Unit):
    def __init__(self, name, allegiance, color, movement_points, tactical_rating):
        super().__init__(name, allegiance, color, movement_points)
        self.tactical_rating = tactical_rating

class Hero(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating):
        super().__init__(name, allegiance, color, movement_points)
        self.combat_rating = combat_rating

class Army(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating, army_type):
        super().__init__(name, allegiance, color, movement_points)
        self.combat_rating = combat_rating
        self.army_type = army_type  # Infantry, cavalry, minotaur, hobgoblin, thanoi

class Fleet(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating, movement_allowance):
        super().__init__(name, allegiance, color, movement_points)
        self.combat_rating = combat_rating
        self.movement_allowance = movement_allowance  # Hex sides for rivers
        self.carrying_army = None  # Can carry one army

    def carry_army(self, army):
        self.carrying_army = army

class FlyingUnit(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating, flying_type, movement_allowance):
        super().__init__(name, allegiance, color, movement_points)
        self.combat_rating = combat_rating
        self.flying_type = flying_type  # dragon, gryphoon, pegasus
        self.movement_allowance = movement_allowance
        self.carrying_army = None

    def carry_army(self, army):
        if self.flying_type != "dragon":
            self.carrying_army = army


