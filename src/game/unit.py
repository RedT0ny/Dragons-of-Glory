class Unit:
    """
    Base class for all units in the game.

    :ivar name: The name of the unit.
    :type name: str
    :ivar type: The type of the unit ('infantry', 'cavalry', 'general', 'admiral', 'hero', 'fleet', 'flight').
    :type unit_type: str
    :ivar race: The race of the unit (e.g., 'draconian', 'dragon', 'goblin', 'hogboblin', 'human', 'solamnic', 'dwarf', 'elf', 'griffon', 'kender', 'minotaur', 'ogre', 'pegasus', 'thanoi', 'undead').
    :type race: str
    :ivar allegiance: The allegiance of the unit (e.g., 'Highlord', 'Neutral', 'Whitesone').
    :type allegiance: str
    :ivar land: The country or faction the unit belongs to.
    :type land: str
    :ivar combat_rating: The combat rating of the unit.
    :type combat_rating: int
    :ivar movement: The movement points available for the unit.
    :type movement: int
    :ivar position: The current position of the unit on the map (e.g., hex coordinates).
    :type position: duple(int, int)
    :ivar terrain_affinity: The terrain affinity of the unit.
    :type terrain_affinity: str
    :ivar status: The current status of the unit (e.g., 'inactive', 'active', 'depleted', 'reserve', 'destroyed').
    :type status: str
    """
    def __init__(self, name, unit_type, rating, movement, race='human', land=None,
                 terrain_affinity=None, status='inactive'):
        self.name = name
        self.unit_type = unit_type
        self.race = race
        self.allegiance = 'neutral'  # Whitesone, Highlord, neutral
        self.land = land
        self.combat_rating = rating # Combat rating for the unit
        self.movement = movement  # Movement points for the unit
        self.position = (None,None) # Current position on the map (hex coordinates)
        self.terrain_affinity = terrain_affinity  # Terrain affinity for the unit
        self.equipment = None
        self.status = status  # inactive, active, depleted, reserve, destroyed
        self.attacked_this_turn = False

    @property
    def is_on_map(self):
        """Checks if the unit is currently active or depleted on the hex grid."""
        return self.status in ('active', 'depleted')

    def apply_combat_loss(self):
        """
        Transitions status based on Rule 7.6.
        Leaders/Heroes/Wings go straight to destroyed.
        Others step down: Active -> Depleted -> Reserve.
        """
        # Rule: Leaders, Heroes, and Wings cannot be depleted or replaced
        is_permanent = (isinstance(self, (Leader, Hero, Wing)) or
                       self.unit_type in ('general', 'admiral', 'hero', 'wing'))

        if self.status == 'active':
            if is_permanent:
                self.status = 'destroyed'
            else:
                self.status = 'depleted'
        elif self.status == 'depleted':
            self.status = 'reserve'
        elif self.status == 'reserve':
            self.status = 'destroyed'

    def eliminate(self):
        """Immediate transition to destroyed/reserve based on type (Rule 7.6 'E' result)."""
        if isinstance(self, (Leader, Hero, Wing)):
            self.status = 'destroyed'
        else:
            self.status = 'reserve'

    def move(self, new_position):
        self.position = new_position

    def is_leader(self):
        return self.unit_type == 'general' or self.unit_type == 'admiral'

    def get_land(self):
        return self.land

class Leader(Unit):
    """
    Leader unit class.

    :ivar tactical_rating: Tactical rating for leaders.
    :type tactical_rating: int
    """
    def __init__(self, name, rating, allegiance, movement):
        super().__init__(name, rating, allegiance, movement)
        self.combat_rating = 0
        self.tactical_rating = rating

class Hero(Unit):
    def __init__(self, name, allegiance, color, movement, combat_rating, tactical_rating=0):
        super().__init__(name, allegiance, color, movement)
        self.combat_rating = combat_rating
        self.tactical_rating = tactical_rating

class Army(Unit):
    def __init__(self, name, allegiance, color, movement, combat_rating, army_type):
        super().__init__(name, allegiance, color, movement)
        self.combat_rating = combat_rating
        self.army_type = army_type  # Infantry, cavalry, minotaur, hobgoblin, thanoi

class Fleet(Unit):
    def __init__(self, name, allegiance, color, movement, combat_rating,):
        super().__init__(name, allegiance, color, movement, combat_rating)
        self.combat_rating = combat_rating
        self.carrying_army = None  # Can carry one army

    def carry_army(self, army):
        self.carrying_army = army

class Wing(Unit):
    def __init__(self, name, allegiance, color, movement, combat_rating):
        super().__init__(name, allegiance, color, movement, combat_rating)
        self.carrying_army = None

    def carry_army(self, army):
        if self.race != "dragon":
            self.carrying_army = army


