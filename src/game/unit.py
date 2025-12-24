class Unit:
    """
    Base class for all units in the game.

    :ivar name: The name of the unit.
    :type name: str
    :ivar unit_type: The type of the unit ('infantry', 'cavalry', 'general', 'admiral', 'hero', 'fleet', 'flight').
    :type unit_type: str
    :ivar race: The race of the unit (e.g., 'draconian', 'dragon', 'goblin', 'hogboblin', 'human', 'solamnic', 'dwarf', 'elf', 'griffon', 'kender', 'minotaur', 'ogre', 'pegasus', 'thanoi', 'undead').
    :type race: str
    :ivar allegiance: The allegiance of the unit (e.g., 'Highlord', 'Neutral', 'Whitesone').
    :type allegiance: str
    :ivar land: The country the unit belongs to.
    :type land: str
    :ivar color: The color representation for the unit.
    :type color: str
    :ivar combat_rating: The combat rating of the unit.
    :type combat_rating: int
    :ivar movement: The movement points available for the unit.
    :type movement: int
    :ivar position: The current position of the unit on the map (e.g., hex coordinates).
    :type position: duple(int, int)
    :ivar terrain_affinity: The terrain affinity of the unit.
    :type terrain_affinity: str
    :ivar status: The current status of the unit (e.g., 'inactive', 'active', 'depleted', 'reserve').
    :type status: str
    :ivar text_style: The visual style or theme for the unit.
    :type text_style: str
    """
    def __init__(self, name, unit_type, combat_rating, race='human', allegiance='neutral', land=None, color, movement, position,
                 terrain_affinity=None, equipment, status='inactive', text_style='default'):
        self.name = name
        self.unit_type = unit_type
        self.race = race
        self.allegiance = allegiance  # Whitesone, Highlord, neutral
        self.land = land
        self.color = color  # Color for the unit, e.g., 'red', 'blue'
        self.combat_rating = combat_rating # Combat rating for the unit
        self.movement = movement  # Movement points for the unit
        self.position = position
        self.terrain_affinity = terrain_affinity  # Terrain affinity for the unit
        self.equipment = equipment
        self.status = status
        self.text_style = text_style

    def move(self, new_position):
        self.position = new_position

    def take_damage(self, amount):
        self.health -= amount
        if self.health <= 0:
            self.status = 'depleted'

    def is_alive(self):
        return self.health > 0 and self.status == 'active'

"""
    Subclasses for specific unit types.
    :ivar tactical_rating: Tactical rating for leaders.
    :type tactical_rating: int
    :ivar combat_rating: Combat rating for heroes, armies, fleets, and flying units.
    :type combat_rating: int
    :ivar army_type: Type of army (infantry, cavalry).
    :type army_type: str
    :ivar flying_type: Type of flying unit (dragon, griffon, pegasus).
    :type flying_type: str
"""
class Leader(Unit):
    def __init__(self, name, allegiance, color, movement_points, tactical_rating):
        super().__init__(name, allegiance, color, movement_points)
        self.tactical_rating = tactical_rating

class Hero(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating, tactical_rating=0):
        super().__init__(name, allegiance, color, movement_points)
        self.tactical_rating = tactical_rating

class Army(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating, army_type):
        super().__init__(name, allegiance, color, movement_points)
        self.combat_rating = combat_rating
        self.army_type = army_type  # Infantry, cavalry, minotaur, hobgoblin, thanoi

class Fleet(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating,):
        super().__init__(name, allegiance, color, movement_points, combat_rating)
        self.combat_rating = combat_rating
        self.carrying_army = None  # Can carry one army

    def carry_army(self, army):
        self.carrying_army = army

class Flight(Unit):
    def __init__(self, name, allegiance, color, movement_points, combat_rating):
        super().__init__(name, allegiance, color, movement_points, combat_rating)
        self.carrying_army = None

    def carry_army(self, army):
        if self.race != "dragon":
            self.carrying_army = army


