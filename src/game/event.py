"""Game event and asset systems.

This module defines the core runtime models for in-game events and
equippable/consumable assets. Events are conditionally triggered by game
state and produce side effects. Assets are items that can be equipped to
units, providing bonuses subject to requirements, or consumed for an
immediate effect.
"""

from typing import Any, Callable, Optional

from src.content.tools import TextFormatter
from src.content.translator import Translator
from src.content.specs import (
    RequirementType,
    ASSET_REQUIREMENTS,
    UnitRace,
    UnitType,
    AssetType
)

translator = Translator()

class Event:
    """A game event that can be triggered by game state conditions.

    Each Event wraps an EventSpec together with callable trigger and
    effect functions. It tracks how many times it has fired and
    deactivates itself once the maximum occurrence count is reached.
    """

    def __init__(self, spec: 'EventSpec', trigger_func: Callable[[Any], bool], effect_func: Callable[[Any], None]) -> None:
        self.spec = spec
        self.id = spec.id
        self.description = spec.description
        self.trigger = trigger_func
        self.effect = effect_func
        self.occurrence_count = 0
        self.is_active = True

    def check_trigger(self, game_state) -> bool:
        """Check whether this event's trigger condition is met.

        Returns False if the event is inactive or has already fired the
        maximum number of times.
        """
        if not self.is_active or self.occurrence_count >= self.spec.max_occurrences:
            return False
        return self.trigger(game_state)

    def activate(self, game_state) -> None:
        """Run the event if its trigger condition is satisfied."""
        if self.check_trigger(game_state):
            self.force_activate(game_state)

    def force_activate(self, game_state) -> None:
        """Execute the event effect immediately, bypassing trigger checks."""
        self.effect(game_state)
        self.occurrence_count += 1
        if self.occurrence_count >= self.spec.max_occurrences:
            self.deactivate()

    def deactivate(self) -> None:
        """Mark this event as inactive so it will not trigger again."""
        self.is_active = False


class Asset:
    """An in-game asset that can be equipped to a unit or consumed.

    Assets are instantiated from an AssetSpec and carry requirements,
    bonuses, and type information. Artifact-type assets can be equipped
    to units if they satisfy all requirements. Consumable assets provide
    a one-shot effect.
    """

    def __init__(self, spec, instance_id: Optional[str] = None):
        self.spec = spec
        self.id = instance_id if instance_id else spec.id
        self.base_id = spec.id
        self.instance_num = int(instance_id.split('_')[-1]) if instance_id and '_' in instance_id else 0
        self.description = spec.description
        self.bonus = spec.bonus
        self.requirements = spec.requirements
        self.is_consumable = spec.is_consumable
        self.asset_type = AssetType(spec.asset_type)

        self.owner = None
        self.assigned_to = None

    @property
    def is_equippable(self) -> bool:
        """Whether this asset can be equipped (only ARTIFACT type)."""
        return self.asset_type == AssetType.ARTIFACT

    def can_equip(self, unit, log_reason=False) -> bool:
        """Check if *unit* can equip this asset based on its requirements.

        Parameters
        ----------
        unit :
            The unit to test against.
        log_reason : bool
            If True, print a human-readable message explaining why the
            check failed.

        Returns
        -------
        bool
            True if the unit satisfies all requirements and the asset
            is equippable.
        """
        unit_id = TextFormatter.format_unit_log_string(unit)
        asset_id = translator.get_asset_name(self.id)
        if not self.is_equippable:
            if log_reason:
                print(f"Asset '{asset_id}' is not equippable.")
            return False

        if not unit.is_on_map:
            if log_reason:
                print(f"Cannot equip '{asset_id}' to '{unit_id}': Unit is not on the map.")
            return False

        for requirement in self.requirements:
            req_type = requirement.get("type")
            req_value = requirement.get("value")

            if not self._check_requirement(unit, req_type, req_value):
                if log_reason:
                    print(f"Cannot equip '{asset_id}' to '{unit_id}': Requirement {req_type}='{req_value}' failed.")
                return False
        return True


    def _check_requirement(self, unit, req_type, req_value) -> bool:
        """Evaluate a single requirement against a unit.

        Supported requirement types are defined in
        :class:`src.content.specs.RequirementType`.
        """
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
            if req_value == "leader":
                return unit.is_leader()
            if req_value == "army":
                return unit.is_army()
            return hasattr(unit, 'unit_type') and unit.unit_type.value == req_value

        elif req_type == RequirementType.ITEM.value:
            return hasattr(unit, 'equipment') and any(item.id == req_value for item in unit.equipment)

        elif req_type == RequirementType.CUSTOM.value:
            return callable(req_value) and req_value(unit)

        return False

    def apply_to(self, unit, on_assign_callback=None) -> None:
        """Equip this asset to *unit*, applying all runtime effects.

        Parameters
        ----------
        unit :
            The target unit.
        on_assign_callback : callable or None
            Optional callback invoked after a successful assignment.
        """
        if self.can_equip(unit, log_reason=True):
            if not hasattr(unit, 'equipment'):
                unit.equipment = []
            if self in unit.equipment:
                return
            unit.equipment.append(self)
            self.assigned_to = unit
            self._apply_runtime_effects(unit)
            if on_assign_callback is not None:
                on_assign_callback(self)
            unit_id = TextFormatter.format_unit_log_string(unit)
            asset_id = translator.get_asset_name(self.base_id) + (' #'+ str(self.instance_num) if self.instance_num > 1 else '')
            print(f"'{unit_id}' equipped '{asset_id}'!")

    def remove_from(self, unit) -> None:
        """Unequip this asset from *unit*, reversing runtime effects."""
        if hasattr(unit, 'equipment') and self in unit.equipment:
            unit.equipment.remove(self)
        self._remove_runtime_effects(unit)
        self.assigned_to = None

    def _apply_runtime_effects(self, unit) -> None:
        """Apply bonus effects that modify unit behaviour at runtime."""
        if not isinstance(self.bonus, dict):
            return
        if self.bonus.get("other") == "emperor" and hasattr(unit, "is_leader") and unit.is_leader():
            unit._unit_type_override = UnitType.EMPEROR

    def _remove_runtime_effects(self, unit) -> None:
        """Reverse runtime effects when the asset is unequipped."""
        if not isinstance(self.bonus, dict):
            return
        if self.bonus.get("other") == "emperor":
            other_emperor_artifacts = [
                a for a in getattr(unit, "equipment", []) or []
                if a is not self and isinstance(getattr(a, "bonus", None), dict) and a.bonus.get("other") == "emperor"
            ]
            if not other_emperor_artifacts:
                unit._unit_type_override = None

    def use(self, game_state) -> None:
        """Consume this asset, executing its one-shot bonus effect."""
        if self.is_consumable and callable(self.bonus):
            self.bonus(game_state)
            if self.assigned_to and hasattr(self.assigned_to, 'equipment'):
                self.assigned_to.equipment.remove(self)
            self.assigned_to = None


def check_requirements(req, active_player, game_state) -> bool:
    """Evaluate a generic requirement dict against the current game state.

    Parameters
    ----------
    req : dict
        Requirement descriptor with at least a ``"type"`` key.
    active_player :
        The player whose assets / allegiances are checked.
    game_state :
        The full game state, providing access to countries etc.

    Returns
    -------
    bool
        True when the requirement is satisfied.
    """
    req_type = req.get('type')
    req_id = req.get('id')
    req_val = req.get('value')

    if req_type == "asset":
        return active_player.has_asset(req_id)

    if req_type == "country_active":
        country = game_state.countries.get(req_id)
        return country and country.allegiance == active_player.allegiance

    return False
