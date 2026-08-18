"""Game event and asset systems.

This module defines the core runtime models for in-game events and
equippable/consumable assets. Events are conditionally triggered by game
state and produce side effects. Assets are items that can be equipped to
units, providing bonuses subject to requirements, or consumed for an
immediate effect.
"""

from typing import Any, Callable, Optional

from src.content.specs import (
    RequirementType,
    ASSET_REQUIREMENTS,
    UnitType,
    AssetType
)
from src.content.tools import TextFormatter
from src.content.translator import Translator

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

    @property
    def display_name(self) -> str:
        """Human-readable event name from the locale files."""
        return translator.get_event_name(self.id)


class Asset:
    """An in-game asset that can be equipped to a unit or consumed.

    Assets are instantiated from an AssetSpec and carry requirements,
    bonuses, and type information. Artifact-type assets can be equipped
    to units if they satisfy all requirements. Consumable assets provide
    a one-shot effect.

    Assignment is permanent from the player's perspective (cannot be
    freely reassigned after the carrier has moved or attacked). When a
    carrier is permanently destroyed, the asset is destroyed with it.
    Army merges transfer a single asset to the surviving army.
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

    @property
    def display_name(self) -> str:
        """Human-readable asset name, including instance number when present."""
        name = translator.get_asset_name(self.base_id)
        if self.instance_num > 0:
            return f"{name} #{self.instance_num}"
        return name

    def get_equip_failure_reason(self, unit) -> Optional[str]:
        """Return a human-readable reason why *unit* cannot equip this asset.

        Returns ``None`` when assignment is allowed.
        """
        if unit is None:
            return "No unit selected."

        if not self.is_equippable:
            return f"'{self.display_name}' is not equippable."

        if self.assigned_to is not None and self.assigned_to is not unit:
            carrier = TextFormatter.format_unit_log_string(self.assigned_to)
            return f"'{self.display_name}' is already assigned to '{carrier}'."

        if not getattr(unit, "is_on_map", False):
            return "Unit is not on the map."

        existing = [a for a in (getattr(unit, "equipment", None) or []) if a is not self]
        if existing:
            return "Unit already carries an asset."

        for requirement in self.requirements or []:
            req_type = requirement.get("type")
            req_value = requirement.get("value")
            if not self._check_requirement(unit, req_type, req_value):
                return self._format_requirement_failure(req_type, req_value)

        return None

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
        reason = self.get_equip_failure_reason(unit)
        if reason is None:
            return True
        if log_reason:
            unit_id = TextFormatter.format_unit_log_string(unit) if unit is not None else "None"
            print(f"Cannot equip '{self.display_name}' to '{unit_id}': {reason}")
        return False

    def can_unassign_from(self, unit) -> tuple[bool, Optional[str]]:
        """Whether this asset may be unassigned from *unit* by the player.

        An asset cannot be unassigned if the carrier has moved or attacked
        this turn.
        """
        if unit is None:
            return False, "No unit selected."
        if self.assigned_to is not None and self.assigned_to is not unit:
            return False, "Asset is not assigned to the selected unit."
        if getattr(unit, "moved_this_turn", False):
            return False, "Cannot unassign: the unit has moved this turn."
        if getattr(unit, "attacked_this_turn", False):
            return False, "Cannot unassign: the unit has attacked this turn."
        return True, None

    @staticmethod
    def _format_requirement_failure(req_type, req_value) -> str:
        """Build a readable message for a failed equip requirement."""
        if isinstance(req_value, (list, tuple)):
            req_value = " or ".join(str(v) for v in req_value)
        if req_type == RequirementType.RACE.value:
            return f"Unit race does not match requirement '{req_value}'."
        if req_type == RequirementType.TRAIT.value:
            return f"Unit does not have required trait '{req_value}'."
        if req_type == RequirementType.ALLEGIANCE.value:
            return f"Unit allegiance does not match requirement '{req_value}'."
        if req_type == RequirementType.UNIT_TYPE.value:
            return f"Unit type does not match requirement '{req_value}'."
        if req_type == RequirementType.ITEM.value:
            return f"Unit is missing required item '{req_value}'."
        if req_type == RequirementType.CUSTOM.value:
            return "Unit does not satisfy a custom requirement."
        return f"Requirement {req_type}='{req_value}' failed."

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
            values = req_value if isinstance(req_value, (list, tuple)) else [req_value]
            for v in values:
                if v == "leader":
                    if unit.is_leader():
                        return True
                elif v == "army":
                    if unit.is_army():
                        return True
                elif hasattr(unit, 'unit_type') and unit.unit_type and unit.unit_type.value == v:
                    return True
            return False

        elif req_type == RequirementType.ITEM.value:
            return hasattr(unit, 'equipment') and any(item.id == req_value for item in unit.equipment)

        elif req_type == RequirementType.CUSTOM.value:
            return callable(req_value) and req_value(unit)

        return False

    def apply_to(self, unit, on_assign_callback=None) -> bool:
        """Equip this asset to *unit*, applying all runtime effects.

        Parameters
        ----------
        unit :
            The target unit.
        on_assign_callback : callable or None
            Optional callback invoked after a successful assignment.

        Returns
        -------
        bool
            True if the asset was successfully equipped.
        """
        if not self.can_equip(unit, log_reason=True):
            return False
        if not hasattr(unit, 'equipment'):
            unit.equipment = []
        if self in unit.equipment:
            return True
        unit.equipment.append(self)
        self.assigned_to = unit
        self._apply_runtime_effects(unit)
        if on_assign_callback is not None:
            on_assign_callback(self)
        unit_id = TextFormatter.format_unit_log_string(unit)
        print(f"'{unit_id}' equipped '{self.display_name}'!")
        return True

    def remove_from(self, unit, force: bool = False) -> bool:
        """Unequip this asset from *unit*, reversing runtime effects.

        Parameters
        ----------
        unit :
            The unit currently carrying the asset.
        force : bool
            When True, bypass the moved/attacked unassign restriction
            (used for combat consumption, destruction, and merges).

        Returns
        -------
        bool
            True if the asset was removed (or was not equipped).
        """
        if unit is None:
            self.assigned_to = None
            return True

        if not force:
            allowed, _reason = self.can_unassign_from(unit)
            if not allowed:
                return False

        if hasattr(unit, 'equipment') and self in unit.equipment:
            unit.equipment.remove(self)
        self._remove_runtime_effects(unit)
        if self.assigned_to is unit:
            self.assigned_to = None
        elif self.assigned_to is None:
            pass
        return True

    def transfer_to(self, new_unit) -> bool:
        """Move this asset from its current carrier to *new_unit*.

        Used when armies merge. Bypasses player unassign restrictions and
        does not re-check equip requirements (merge keeps unit identity of
        the same replacement group).
        """
        if new_unit is None:
            return False

        old_unit = self.assigned_to
        if old_unit is new_unit:
            return True

        if old_unit is not None:
            self.remove_from(old_unit, force=True)

        if not hasattr(new_unit, "equipment"):
            new_unit.equipment = []

        # One-asset-per-unit rule: do not overwrite an existing carrier asset.
        if any(a is not self for a in new_unit.equipment):
            return False

        if self not in new_unit.equipment:
            new_unit.equipment.append(self)
        self.assigned_to = new_unit
        self._apply_runtime_effects(new_unit)
        return True

    def destroy(self) -> None:
        """Permanently destroy this asset (removed from carrier and owner pool)."""
        unit = self.assigned_to
        if unit is not None:
            self.remove_from(unit, force=True)
        elif unit is None:
            # Ensure equipment lists cannot retain a dangling reference.
            pass

        owner = self.owner
        if owner is not None and hasattr(owner, "assets"):
            owner.assets.pop(self.id, None)
        self.owner = None
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
            carrier = self.assigned_to
            if carrier is not None:
                self.remove_from(carrier, force=True)
            self.assigned_to = None
            if self.owner is not None and hasattr(self.owner, "assets"):
                self.owner.assets.pop(self.id, None)
            self.owner = None


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
