from operator import truediv


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
    :ivar land: The country or faction the unit belongs to.
    :type land: str
    :ivar combat_rating: The combat rating of the unit.
    :type combat_rating: int
    :ivar tactical_rating: The tactical rating of the unit.
    :type tactical_rating: int
    :ivar movement: The movement points available for the unit.
    :type movement: int
    :ivar position: The current position of the unit on the map (e.g., hex coordinates).
    :type position: duple(int, int)
    :ivar status: The current status of the unit (e.g., 'inactive', 'active', 'depleted', 'reserve', 'destroyed').
    :type status: str
    """
    def __init__(self, name, unit_type, combat_rating, tactical_rating, movement, race='human', land=None,
                 status='inactive'):
        self.name = name
        self.unit_type = unit_type
        self.race = race
        self.allegiance = 'neutral'  # Whitesone, Highlord, neutral
        self.land = land
        self.combat_rating = combat_rating # Combat rating for the unit
        self.tactical_rating = tactical_rating  # Tactical rating for the unit
        self.movement = movement  # Movement points for the unit
        self.position = (None,None) # Current position on the map (hex coordinates)
        self.equipment = None
        self.status = status  # inactive, active, depleted, reserve, destroyed
        self.attacked_this_turn = False

    @property
    def is_on_map(self):
        """Checks if the unit is currently active or depleted on the hex grid."""
        return self.status in ('active', 'depleted')

    def apply_combat_loss(self, dmg_type, must_retreat=False):
        """
        Transitions status based on Rule 7.6.
        Leaders/Heroes/Wings go straight to destroyed.
        Others step down: Active -> Depleted -> Reserve.

        :ivar dmg_type: 'D' for Depleted, 'E' for Eliminated.
        :type dmg_type: str
        :ivar must_retreat: True if the unit must retreat after taking damage.
        :type must_retreat: bool
        """
        # Rule: Leaders, Heroes, and Wings cannot be depleted or replaced
        if isinstance(self, (Leader, Hero, Wing)):
            self.status = 'destroyed'

        if dmg_type == 'E':
            self.eliminate()
        elif dmg_type == 'D':
            self.deplete()

        if self.is_on_map and must_retreat:
            self.retreat()

        return

    def eliminate(self):
        self.status = 'reserve'

    def deplete(self):
        if self.status == 'active':
            self.status = 'depleted'
        elif self.status == 'depleted':
            self.status = 'reserve'
        elif self.status == 'reserve':
            self.status = 'destroyed'

    def move(self, new_position):
        self.position = new_position

    def retreat(self):
        #TODO: Implement retreat logic
        return NotImplementedError

    def get_land(self):
        return self.land

class Leader(Unit):
    """
    Leader unit class.

    :ivar tactical_rating: Tactical rating for leaders.
    :type tactical_rating: int
    """
    def __init__(self, name, unit_type, tactical_rating, movement, race):
        super().__init__(name, unit_type, 0, tactical_rating, movement, race)
    # Note: Don't implement tactical radius and command control for the moment.

    def is_leader(self):
        return True

class Hero(Unit):
    def __init__(self, name, allegiance, movement, combat_rating, tactical_rating=0):
        super().__init__(name, allegiance, movement)
        self.combat_rating = combat_rating
        self.tactical_rating = tactical_rating

class Army(Unit):
    """
    Represents an army, which is a specialized type of unit with combat capabilities
    and distinct attributes such as combat rating and terrain affinity.

    This class builds upon the basic Unit class by adding features key to military
    units, such as specifying a combat rating and assigning terrain affinity. It can
    be used in simulations or games that model army behavior and attributes.

    Attributes:
        combat_rating: int
            A numerical representation of the army's combat effectiveness in battle.
        terrain_affinity: Optional[str]
            The type of terrain where the army has an advantage. Set to None by default.
    """
    def __init__(self, name, allegiance, movement, combat_rating, race):
        super().__init__(name, allegiance, movement, race)
        self.combat_rating = combat_rating
        self.terrain_affinity = None  # Terrain affinity for the unit

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


