from typing import Optional, Tuple, List, Any
from src.content.specs import UnitSpec, UnitType, UnitRace, UnitState
from src.content.constants import NEUTRAL, HL, WS

class Unit:
    """
    Base class for all units in the game.
    Now uses UnitSpec for static attributes (The Flyweight Pattern).

    :ivar spec: The UnitSpec for this unit.
    :type spec: UnitSpec
    :ivar ordinal: The unit's order of battle.
    :type ordinal: int
    :ivar equipment: A list of equipment the unit is equipped with.
    :type equipment: list[Equipment]
    """
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        self.spec = spec
        
        # Identity
        self.id = spec.id  # The slug from units.csv
        self.ordinal = ordinal # Distinguishes units of same type (e.g. 1st vs 2nd Division)

        # Dynamic State
        # Allow spec.status to be a string or Enum, defaulting to INACTIVE
        raw_status = spec.status if spec.status else UnitState.INACTIVE
        if isinstance(raw_status, str):
            try:
                self.status = UnitState[raw_status.upper()]
            except KeyError:
                self.status = UnitState.INACTIVE
        else:
            self.status = raw_status

        self.position: Tuple[Optional[int], Optional[int]] = (None, None)
        self.equipment: List[Any] = [] # List of Artifact objects

        # Turn-based flags
        self.is_transported = False
        self.attacked_this_turn = False
        self.moved_this_turn = False

        # Temporary effects
        self._movement_override = None

        # --- Property Proxies (Read from Spec unless overridden) ---

    @property
    def unit_type(self) -> Optional[UnitType]:
        return UnitType(self.spec.unit_type) if self.spec.unit_type else None

    @property
    def race(self) -> Optional[UnitRace]:
        return UnitRace(self.spec.race) if self.spec.race else None

    @property
    def allegiance(self) -> str:
        # FIX: Check if an override exists before falling back to the spec
        return getattr(self, '_allegiance_override', self.spec.allegiance or NEUTRAL)

    @allegiance.setter
    def allegiance(self, value):
        # We might need to change allegiance dynamically (e.g. diplomacy)
        # But we shouldn't modify the spec.
        # Ideally, we should shadow the spec value if it changes.
        self._allegiance_override = value

    # We need a getter that checks the override first
    def get_allegiance(self):
        return getattr(self, '_allegiance_override', self.spec.allegiance or NEUTRAL)

    @property
    def land(self) -> Optional[str]:
        return self.spec.country

    @land.setter
    def land(self, value):
        # Allow overriding land (e.g. for dynamic ownership if needed, though rare)
        self.spec.country = value # CAUTION: Modifying spec is risky if shared.
        # Better to have a self._land_override like allegiance if this changes often.
        # For now, land (origin) usually doesn't change.

    @property
    def tactical_rating(self) -> int:
        return self.spec.tactical_rating or 0

    @property
    def combat_rating(self) -> int:
        """Calculates total combat rating including equipment bonuses."""
        total = self.spec.combat_rating or 0
        for item in self.equipment:
            # item is an Artifact object with a 'bonus' attribute
            if hasattr(item, 'bonus') and isinstance(item.bonus, int):
                total += item.bonus
            elif hasattr(item, 'bonus') and isinstance(item.bonus, dict):
                # Handle dict bonus e.g. {'combat': 2}
                total += item.bonus.get('combat', 0)
        return total

    @property
    def movement(self) -> int:
        """Returns movement points, handling overrides and transport."""
        # 1. Check for override
        if self._movement_override is not None:
            base = self._movement_override
        else:
            base = self.spec.movement or 0

        # 2. Wizards move logic (Teleport essentially)
        if self.unit_type == UnitType.WIZARD:
            return base

        # 3. Transport logic
        # Assuming passengers is defined in subclasses or mixed-in
        has_passengers = getattr(self, 'passengers', False)
        if has_passengers and self.unit_type != UnitType.CITADEL:
            return base // 2

        return base

    @movement.setter
    def movement(self, value):
        self._movement_override = value

    @property
    def is_on_map(self) -> bool:
        return self.status in UnitState.on_map_states()

    def is_leader(self) -> bool:
        return False # Base unit is not a leader

    def is_army(self) -> bool:
        return False # Base unit is not an army either

    # --- State Logic ---

    def apply_combat_loss(self, dmg_type: str, must_retreat: bool = False):
        one_hit_units = {UnitType.GENERAL, UnitType.ADMIRAL, UnitType.HERO,
                         UnitType.WING, UnitType.EMPEROR, UnitType.WIZARD, UnitType.CITADEL}

        # Use property to get Enum type safely
        u_type = self.unit_type

        if u_type in one_hit_units:
            self.destroy()
            return

        if dmg_type == 'E':
            self.eliminate()
        elif dmg_type == 'D':
            self.deplete()

        if self.is_on_map and must_retreat:
            self.retreat()

    def activate(self):
        """Moves to Active status."""
        self.status = UnitState.ACTIVE

    def ready(self):
        """Moves to Ready status."""
        self.status = UnitState.READY

    def eliminate(self):
        """Moves to Reserve (can be rebuilt)."""
        if self.status not in [UnitState.RESERVE, UnitState.DESTROYED]:
            self.status = UnitState.RESERVE
            self.position = (None, None)

    def deplete(self):
        """Active -> Depleted -> Reserve."""
        if self.status == UnitState.ACTIVE:
            self.status = UnitState.DEPLETED
        elif self.status == UnitState.DEPLETED:
            self.eliminate()

    def destroy(self):
        """Permanently removed."""
        self.status = UnitState.DESTROYED
        self.position = (None, None)

    def move(self, new_position: Tuple[int, int]):
        self.position = new_position
        self.moved_this_turn = True

    def retreat(self):
        # Placeholder for retreat logic
        pass

    def to_dict(self) -> dict:
        return {
            "unit_id": self.id,
            "ordinal": self.ordinal,
            "position": list(self.position),
            "status": self.status.name,
            "is_transported": self.is_transported,
            "attacked_this_turn": self.attacked_this_turn,
            "moved_this_turn": self.moved_this_turn
        }

    def load_state(self, state_data: dict):
        pos = state_data.get("position")
        self.position = tuple(pos) if pos else (None, None)

        status_str = state_data.get("status")
        if status_str and hasattr(UnitState, status_str):
            self.status = UnitState[status_str]

        self.is_transported = state_data.get("is_transported", False)
        self.attacked_this_turn = state_data.get("attacked_this_turn", False)
        self.moved_this_turn = state_data.get("moved_this_turn", False)

class Leader(Unit):
    """
    Leader unit class.
    Leader unit types: admiral, emperor, general, highlord, wizard
    """
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)

    def is_leader(self) -> bool:
        return True

class Wizard(Leader):
    """
    Wizards can move to any hex on the map (except enemy hexes) once per turn.
    """
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)


class Fleet(Unit):
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)
        self.passengers = []
        self.river_hexside = None

    def can_carry(self, unit):
        """Ships carry one ground army and any number of leaders."""
        if unit.is_leader(): return True
    
        # Check if an army is already aboard
        has_army = any(not p.is_leader() for p in self.passengers)
        return not unit.is_leader() and not has_army

    def load_unit(self, unit):
        if self.can_carry(unit):
            self.passengers.append(unit)
            unit.is_transported = True

    def set_river_hexside(self, hexside):
        self.river_hexside = hexside

class Wing(Unit):
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)
        self.passengers = []

    def can_carry(self, unit: Unit) -> bool:
        # Griffons and Pegasi: Can carry 1 Infantry AND 1 Leader
        if self.race in (UnitRace.GRIFFON, UnitRace.PEGASUS):
            # Check what we already have aboard
            has_inf = any(p.unit_type == UnitType.INFANTRY for p in self.passengers)
            has_ldr = any(p.is_leader() for p in self.passengers)

            # Incoming unit is Infantry?
            if unit.unit_type == UnitType.INFANTRY:
                return not has_inf # Can carry if we don't have one yet

            # Incoming unit is Leader?
            if unit.is_leader():
                return not has_ldr # Can carry if we don't have one yet

            return False

        # Dragons: 1 Leader (Color/Race matching)
        if self.race == UnitRace.DRAGON:
            if not unit.is_leader() or len(self.passengers) >= 1:
                return False
        
            if self.allegiance == HL:
                # Must match color (land) or be Ariakas (emperor)
                return unit.land == self.land or unit.unit_type == UnitType.EMPEROR
        
            if self.allegiance == WS:
                # Must be Elf or Solamnic
                return unit.race in (UnitRace.ELF, UnitRace.SOLAMNIC)
        return False

    def load_unit(self, unit):
        if self.can_carry(unit):
            self.passengers.append(unit)
            unit.is_transported = True

class FlyingCitadel(Unit):
    """
    A specific unit type that acts as a mobile fortress.
    Inherits from Unit directly (not Wing).
    """
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)
        self.passengers = []

    def can_carry(self, unit: Unit) -> bool:
        if unit.allegiance != HL: return False

        # Check Armies (Infantry or Cavalry)
        # Rule says "Up to three HL armies of any types"
        if unit.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY):
            count = sum(1 for p in self.passengers if p.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY))
            return count < 3

        # Leaders usually travel free of capacity constraints in DL11 rules context
        # (they stack with armies), provided they are Highlord.
        if unit.is_leader():
            return True

        return False

    def load_unit(self, unit: Unit):
        if self.can_carry(unit):
            self.passengers.append(unit)
            unit.is_transported = True

    def get_defense_modifier(self):
        """
        Implements the Location interface method via Duck Typing.
        Rule: 'treat it as a fortified city'.
        City/Port modifier is -2.
        """
        return -2

class Hero(Unit):
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)

class Army(Unit):
    """
    Represents an army (Infantry/Cavalry).
    """
    def __init__(self, spec: UnitSpec, ordinal: int = 1):
        super().__init__(spec, ordinal)
        self.terrain_affinity = spec.terrain_affinity

    def is_army(self) -> bool:
        return True
