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
        self._base_combat_rating = combat_rating # Combat rating for the unit
        self.tactical_rating = tactical_rating  # Tactical rating for the unit
        self._base_movement = movement  # Use internal var for setter/getter
        self.position = (None,None) # Current position on the map (hex coordinates)
        self.equipment = []
        self.status = status # inactive, active, depleted, reserve, destroyed
        self.is_transported = False  # New flag to track transport state
        self.attacked_this_turn = False

    @property
    def combat_rating(self):
        """Calculates total combat rating including equipment bonuses."""
        total = self._base_combat_rating
        for item in self.equipment:
            if isinstance(item.bonus, int):
                total += item.bonus
            # Handle complex logic like "doubled strength" via a flag or callback
        return total

    @property
    def movement(self):
        """Returns movement points, halved if transporting units (except for Citadels)."""
        # Wizards move anywhere, we can handle that in the move logic, 
        # but for consistency we return their base.
        if self.unit_type == "wizard":
            return self._base_movement

        # Check if carrying anything
        has_passengers = hasattr(self, 'passengers') and self.passengers
        
        if has_passengers and self.unit_type != "citadel":
            return self._base_movement // 2
        return self._base_movement

    @movement.setter
    def movement(self, value):
        self._base_movement = value

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

Leader unit types: admiral, emperor, general, highlord, wizard

:ivar tactical_rating: Tactical rating for leaders.
:type tactical_rating: int
    """
    def __init__(self, name, unit_type, tactical_rating, movement, race, land=None):
        super().__init__(name, unit_type, 0, tactical_rating, movement, race, land)

    def is_leader(self):
        return True

class Wizard(Leader):
    """
    Wizards can move to any hex on the map (except enemy hexes) once per turn.
    """
    def __init__(self, name, race, land, allegiance):
        super().__init__(name, "wizard", tactical_rating=3, movement=99, race=race, land=land)
        self.allegiance = allegiance

class Fleet(Unit):
    def __init__(self, name, race, land, allegiance, movement, combat_rating):
        super().__init__(name, "fleet", combat_rating, 0, movement, race, land)
        self.river_hexside = None # Optional attribute when navigating river hexsides
        self.allegiance = allegiance
        self.passengers = [] # List of units currently aboard

    def can_carry(self, unit):
        """Ships carry one ground army and any number of leaders."""
        if unit.is_leader():
            return True
        
        # Check if an army is already aboard
        has_army = any(not p.is_leader() for p in self.passengers)
        if not unit.is_leader() and not has_army:
            return True
        return False

    def load_unit(self, unit):
        if self.can_carry(unit):
            self.passengers.append(unit)
            unit.is_transported = True

    def set_river_hexside(self, hexside):
        self.river_hexside = hexside

class Wing(Unit):
    def __init__(self, name, race, land, allegiance, movement, combat_rating):
        super().__init__(name, "wing", combat_rating, 0, movement, race, land)
        self.allegiance = allegiance
        self.passengers = []

    def can_carry(self, unit):
        # Griffons and Pegasi: 1 Infantry AND 1 Leader
        if self.race in ("griffon", "pegasus"):
            is_inf = (unit.unit_type == "inf")
            is_ldr = unit.is_leader()
            
            if is_inf and any(p.unit_type == "inf" for p in self.passengers):
                return False
            if is_ldr and any(p.is_leader() for p in self.passengers):
                return False
            return is_inf or is_ldr

        # Dragons: 1 Leader (Color/Race matching)
        if self.race == "dragon":
            if not unit.is_leader() or len(self.passengers) >= 1:
                return False
            
            if self.allegiance == "highlord":
                # Must match color (land) or be Ariakas (emperor)
                return unit.land == self.land or unit.unit_type == "emperor"
            
            if self.allegiance == "whitestone":
                # Must be Elf or Solamnic
                return unit.race in ("elf", "solamnic")
        return False

    def load_unit(self, unit):
        if self.can_carry(unit):
            self.passengers.append(unit)
            unit.is_transported = True

    class FlyingCitadel(Unit):
        def __init__(self, name, allegiance):
        # Citadels move 4 hexes, ignore terrain, and have no combat rating themselves
            super().__init__(name, "citadel", 0, 0, 4, race="magic")
            self.allegiance = allegiance
            self.passengers = []

        def can_carry(self, unit):
            # Up to three HL armies of any type.
            armies_aboard = [p for p in self.passengers if p.unit_type in ("inf", "cav")]
            return unit.allegiance == "highlord" and len(armies_aboard) < 3

class Hero(Unit):
    def __init__(self, name, unit_type, combat_rating, tactical_rating, movement):
        super().__init__(name, unit_type, combat_rating, tactical_rating, movement)


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
        super().__init__(name, allegiance, movement, combat_rating, 0, race)
        self.terrain_affinity = None  # Terrain affinity for the unit
