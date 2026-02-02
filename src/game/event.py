from typing import Any, Callable
from ..content.specs import (
    RequirementType,
    ASSET_REQUIREMENTS,
    UnitRace,
    UnitType,
    AssetType
)

class Event:
    def __init__(self, spec: 'EventSpec', trigger_func: Callable[[Any], bool], effect_func: Callable[[Any], None]) -> None:
        self.spec = spec  # Store the whole spec
        self.id = spec.id
        self.description = spec.description
        self.trigger = trigger_func
        self.effect = effect_func
        self.occurrence_count = 0
        self.is_active = True

    def check_trigger(self, game_state):
        if not self.is_active or self.occurrence_count >= self.spec.max_occurrences:
            return False
        return self.trigger(game_state)

    def activate(self, game_state):
        # Conditionally applies effect then deactivates if triggered
        if self.check_trigger(game_state): # E.g. If effects key is "grant_artifact", look artifact up in the global pool and give it to the player.
            self.effect(game_state)
            self.occurrence_count += 1

            # Auto-deactivate if we hit the limit
            if self.occurrence_count >= self.spec.max_occurrences:
                self.deactivate()

    def deactivate(self):
        self.is_active = False

class Asset:
    def __init__(self, spec):
        self.spec = spec
        self.id = spec.id
        self.description = spec.description
        self.bonus = spec.bonus
        self.requirements = spec.requirements
        self.is_consumable = spec.is_consumable
        self.asset_type = AssetType(spec.asset_type)

        self.owner = None
        self.assigned_to = None  # Reference to a Unit object

    @property
    def is_equippable(self):
        return self.asset_type == AssetType.ARTIFACT

    def can_equip(self, unit):
        """
        Check if a unit can equip this asset based on requirements.
        """
        if not self.is_equippable:
            return False

        for requirement in self.requirements:
            req_type = requirement.get("type")
            req_value = requirement.get("value")

            if not self._check_requirement(unit, req_type, req_value):
                return False
        return True

    def _check_requirement(self, unit, req_type, req_value):
        """Check a single requirement against a unit."""
        if req_type == RequirementType.RACE.value:
            required_race = ASSET_REQUIREMENTS["race_requirements"].get(req_value)
            return hasattr(unit, 'race') and unit.race == required_race

        elif req_type == RequirementType.TRAIT.value:
            trait_check = ASSET_REQUIREMENTS["trait_requirements"].get(req_value)
            return trait_check and trait_check(unit)

        elif req_type == RequirementType.ALLEGIANCE.value:
            required_allegiance = ASSET_REQUIREMENTS["allegiance_requirements"].get(req_value)
            return hasattr(unit, 'allegiance') and unit.allegiance == required_allegiance

        elif req_type == RequirementType.UNIT_TYPE.value:
            return hasattr(unit, 'unit_type') and unit.unit_type.value == req_value

        elif req_type == RequirementType.ITEM.value:
            # Check for other items in equipment
            return hasattr(unit, 'equipment') and any(item.id == req_value for item in unit.equipment)

        elif req_type == RequirementType.CUSTOM.value:
            return callable(req_value) and req_value(unit)

        return False

    def apply_to(self, unit):
        """Apply asset effects to a unit."""
        if self.can_equip(unit):
            if not hasattr(unit, 'equipment'):
                unit.equipment = []
            unit.equipment.append(self)
            self.assigned_to = unit

            # Apply stat bonuses if bonus is a dict
            if isinstance(self.bonus, dict):
                for stat, value in self.bonus.items():
                    current_value = getattr(unit, stat, 0)
                    setattr(unit, stat, current_value + value)

    def remove_from(self, unit):
        """Remove asset effects from a unit."""
        if hasattr(unit, 'equipment') and self in unit.equipment:
            unit.equipment.remove(self)

        # Remove stat bonuses if bonus is a dict
        if isinstance(self.bonus, dict):
            for stat, value in self.bonus.items():
                current_value = getattr(unit, stat, 0)
                setattr(unit, stat, max(0, current_value - value))

        self.assigned_to = None

    def use(self, game_state):
        """Use a consumable asset."""
        if self.is_consumable and callable(self.bonus):
            self.bonus(game_state)
            if self.assigned_to and hasattr(self.assigned_to, 'equipment'):
                self.assigned_to.equipment.remove(self)
            self.assigned_to = None

def check_requirements(req, active_player, game_state):
    """Unified generic requirement checker."""
    req_type = req.get('type')
    req_id = req.get('id')
    req_val = req.get('value')

    if req_type == "asset":
        # Check player's private inventory first
        if req_id in active_player.assets:
            return True
        # Check the world state pool second (if you have a global list of discovered assets)
        # if req_id in game_state.global_assets: return True
        return False

    if req_type == "country_active":
        country = game_state.countries.get(req_id)
        return country and country.allegiance == active_player.allegiance

    return False