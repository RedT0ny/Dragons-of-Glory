from typing import Any, Callable
from ..content.specs import (
    RequirementType, 
    ARTIFACT_REQUIREMENTS, 
    UnitRace, 
    UnitType
)

class Event:
    def __init__(self, event_id: str, description: str, trigger: Callable[[Any], bool], effect: Any) -> None:
        self.id = event_id
        self.description = description
        self.trigger = trigger
        self.effect = effect
        self.occurrence_count = 0  # Track how many times it has fired
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

class Artifact:
    def __init__(self, artifact_id, description, bonus, requirements=None, is_consumable=False):
        self.id = artifact_id
        self.description = description
        self.bonus = bonus # Can be int, dict, or a function
        self.requirements = requirements or [] # List of requirement dictionaries
        self.is_consumable = is_consumable
        self.owner = None

    def can_equip(self, unit):
        """
        Check if a unit can equip this artifact based on requirements.
        Requirements format: [{"type": "race", "value": "solamnic"}, {"type": "allegiance", "value": "whitestone"}]
        """
        for requirement in self.requirements:
            req_type = requirement.get("type")
            req_value = requirement.get("value")
            
            if not self._check_requirement(unit, req_type, req_value):
                return False
        return True

    def _check_requirement(self, unit, req_type, req_value):
        """Check a single requirement against a unit."""
        if req_type == RequirementType.RACE.value:
            required_race = ARTIFACT_REQUIREMENTS["race_requirements"].get(req_value)
            return hasattr(unit, 'race') and unit.race == required_race
            
        elif req_type == RequirementType.TRAIT.value:
            trait_check = ARTIFACT_REQUIREMENTS["trait_requirements"].get(req_value)
            return trait_check and trait_check(unit)
            
        elif req_type == RequirementType.ALLEGIANCE.value:
            required_allegiance = ARTIFACT_REQUIREMENTS["allegiance_requirements"].get(req_value)
            return hasattr(unit, 'allegiance') and unit.allegiance == required_allegiance
            
        elif req_type == RequirementType.UNIT_TYPE.value:
            return hasattr(unit, 'unit_type') and unit.unit_type.value == req_value
            
        elif req_type == RequirementType.ITEM.value:
            return hasattr(unit, 'equipment') and any(item.name == req_value for item in unit.equipment)
            
        elif req_type == RequirementType.CUSTOM.value:
            # For custom requirements, req_value should be a callable
            return callable(req_value) and req_value(unit)
            
        return False

    def apply_to(self, unit):
        """Apply artifact effects to a unit."""
        if self.can_equip(unit):
            if not hasattr(unit, 'equipment'):
                unit.equipment = []
            unit.equipment.append(self)
            self.owner = unit
            
            # Apply stat bonuses if bonus is a dict
            if isinstance(self.bonus, dict):
                for stat, value in self.bonus.items():
                    current_value = getattr(unit, stat, 0)
                    setattr(unit, stat, current_value + value)

    def remove_from(self, unit):
        """Remove artifact effects from a unit."""
        if hasattr(unit, 'equipment') and self in unit.equipment:
            unit.equipment.remove(self)
            
        # Remove stat bonuses if bonus is a dict
        if isinstance(self.bonus, dict):
            for stat, value in self.bonus.items():
                current_value = getattr(unit, stat, 0)
                setattr(unit, stat, max(0, current_value - value))
                
        self.owner = None

    def use(self, game_state):
        """Use a consumable artifact."""
        if self.is_consumable and callable(self.bonus):
            self.bonus(game_state)
            if self.owner and hasattr(self.owner, 'equipment'):
                self.owner.equipment.remove(self)
            self.owner = None
