from dataclasses import dataclass
from typing import List

from src.content.constants import HL, NEUTRAL
from src.game.map import Hex
from src.game.unit import Unit


@dataclass
class NeutralEntryDecision:
    """Decision on entering a neutral country."""
    is_neutral_entry: bool
    country_id: str | None = None
    blocked_message: str | None = None
    confirmation_prompt: str | None = None
    invasion_units: List[object] | None = None


class InvasionHandler:
    """Reusable invasion and neutral-entry logic for movement and unboarding flows."""
    def __init__(self, movement_service):
        self.movement_service = movement_service
        self.game_state = movement_service.game_state

    def evaluate_neutral_entry(self, target_hex) -> NeutralEntryDecision:
        """Check whether moving into ``target_hex`` would enter a neutral country.

        Returns a decision telling the caller whether entry is possible and, if so,
        whether it needs player confirmation (HL) or is blocked (Whitestone).
        """
        col, row = target_hex.axial_to_offset()
        country = self.game_state.get_country_by_hex(col, row)
        if not country or country.allegiance != NEUTRAL:
            return NeutralEntryDecision(is_neutral_entry=False)

        country_id = country.id
        if self.game_state.active_player != HL:
            return NeutralEntryDecision(
                is_neutral_entry=True,
                country_id=country_id,
                blocked_message="Whitestone player cannot invade neutral countries.",
            )

        return NeutralEntryDecision(
            is_neutral_entry=True,
            country_id=country_id,
            confirmation_prompt=f"Invade {country_id}?",
        )

    def get_invasion_force(self, country_id, extra_units=None):
        """Assemble the force available to invade a neutral country.

        The force combines two sources:
          * ``extra_units``: caller-supplied units (e.g. units already embarked
            toward the country or standing on its territory); and
          * map stacks: every Highlord control unit (army, wing or citadel) that
            can physically move into a country hex -- whether from a border hex
            adjacent to the country or from a friendly hex connected to one.

        Returns a dict with:
          * ``strength``: total combat rating of the force;
          * ``units``: the units making up the force;
          * ``border_hexes``: friendly hexes directly adjacent to the country;
          * ``connected_hexes``: border hexes plus supporting friendly hexes;
          * ``reason``: None when a force was found, otherwise why it could not be.
        """
        # Only neutral countries can be invaded.
        country = self.game_state.countries.get(country_id)
        if not country or country.allegiance != NEUTRAL:
            return self._result(0, [], reason="Country is not neutral.")

        # The country's territories define the hexes the invasion must reach.
        target_hexes = set(country.territories)
        if not target_hexes:
            return self._result(0, [], reason="Country has no territory.")

        # Caller-supplied units must pass the same eligibility checks as map stacks.
        extra_eligible = self._eligible_extra_units(extra_units, target_hexes)

        # All Highlord stacks on the map, including HL passengers on transports.
        stacks_by_hex = self._hl_stacks_with_passengers()

        # Border hexes = friendly stack hexes that can actually move into the country.
        border_hexes = {
            hex_obj
            for hex_obj, stack_units in stacks_by_hex.items()
            if self._stack_can_invade_from_hex(hex_obj, stack_units, target_hexes)
        }

        # If nothing can move in from the map, the extra units (e.g. an embarked
        # force) may still be enough on their own; otherwise report why there is
        # no force.
        if not border_hexes:
            reason = (
                "No Highlord stacks available."
                if not stacks_by_hex
                else "No eligible Highlord stacks adjacent to the border."
            )
            return self._extra_only_result(extra_eligible, reason)

        # Support hexes: friendly stack hexes reachable from a border hex by
        # marching through other friendly stack hexes. Their units can join too.
        connected_hexes = self._connected_support_hexes(border_hexes, stacks_by_hex.keys())

        # Assemble the force from the connected hexes plus the extra units.
        eligible_units = self._invasion_units_from_connected_hexes(connected_hexes, stacks_by_hex, target_hexes)
        eligible_units = self._merge_distinct_units(eligible_units, extra_eligible)

        return self._result(
            self._invasion_strength(eligible_units),
            eligible_units,
            border_hexes,
            connected_hexes,
        )

    @staticmethod
    def _result(strength, units, border_hexes=None, connected_hexes=None, reason=None):
        """Build the result dict returned by ``get_invasion_force``."""
        return {
            "strength": strength,
            "units": units or [],
            "border_hexes": border_hexes or set(),
            "connected_hexes": connected_hexes or set(),
            "reason": reason,
        }

    def _extra_only_result(self, extra_eligible, failure_reason):
        """Result when only caller-supplied extra units can invade.

        Returns a successful force if extra units exist, otherwise a failure with
        ``failure_reason``.
        """
        return self._result(
            self._invasion_strength(extra_eligible),
            extra_eligible,
            reason=None if extra_eligible else failure_reason,
        )

    @staticmethod
    def _invasion_strength(units):
        """Total invasion strength = sum of positive combat ratings."""
        return sum(
            int(unit.combat_rating)
            for unit in (units or [])
            if int(unit.combat_rating) > 0
        )

    def _hl_stacks_with_passengers(self):
        """Map each hex to its Highlord units, including HL passengers on transports."""
        stacks = {}
        for hex_coords, units in self.game_state.map.unit_map.items():
            stack_units = [u for u in units if u.allegiance == HL and u.is_on_map]
            if not stack_units:
                continue
            hex_obj = Hex(*hex_coords)
            stack_with_passengers = list(stack_units)
            for unit in stack_units:
                passengers = getattr(unit, "passengers", None)
                if passengers:
                    stack_with_passengers.extend(
                        passenger for passenger in passengers if passenger.allegiance == HL
                    )
            stacks[hex_obj] = stack_with_passengers
        return stacks

    def _stack_can_invade_from_hex(self, hex_obj, stack_units, target_hexes) -> bool:
        """Does any control unit in this stack have the MP to enter the country?"""
        return any(
            unit.is_control_unit()
            and not getattr(unit, "invaded_this_turn", False)
            and self.movement_service._unit_can_reach_country(unit, hex_obj, target_hexes)
            for unit in stack_units
        )

    @staticmethod
    def _connected_support_hexes(border_hexes, all_stack_hexes) -> set[Hex]:
        """Flood-fill from the border hexes through other friendly stack hexes.

        Returns every stack hex connected to a border hex by a chain of adjacent
        friendly stack hexes -- those units can march in behind the front line.
        """
        remaining = set(all_stack_hexes) - set(border_hexes)
        connected = set(border_hexes)
        frontier = list(border_hexes)
        while frontier:
            current = frontier.pop()
            for neighbor in current.neighbors():
                if neighbor not in remaining:
                    continue
                remaining.remove(neighbor)
                connected.add(neighbor)
                frontier.append(neighbor)
        return connected

    def _invasion_units_from_connected_hexes(self, connected_hexes, stacks_by_hex, target_hexes) -> list[Unit]:
        """Control units on the connected hexes that can physically enter the country."""
        return [
            unit
            for hex_obj in connected_hexes
            for unit in stacks_by_hex.get(hex_obj, [])
            if unit.is_control_unit()
            and not getattr(unit, "invaded_this_turn", False)
            and self.movement_service._unit_can_reach_country(unit, hex_obj, target_hexes, connected_hexes)
        ]

    def evaluate_unboard_neutral_entry(self, selected_units) -> NeutralEntryDecision:
        """Check whether unboarding the selected units would land in a neutral country."""
        landing = self._collect_unboard_landing_units(selected_units)
        if not landing:
            return NeutralEntryDecision(is_neutral_entry=False)

        country_ids = set()
        invasion_units = []
        for country_id, units in landing.items():
            if not country_id:
                continue
            country = self.game_state.countries.get(country_id)
            if not country or country.allegiance != NEUTRAL:
                continue
            country_ids.add(country_id)
            invasion_units.extend(units)

        if not country_ids:
            return NeutralEntryDecision(is_neutral_entry=False)
        if len(country_ids) > 1:
            return NeutralEntryDecision(
                is_neutral_entry=True,
                blocked_message="Cannot unboard into multiple neutral countries in one action.",
            )

        country_id = next(iter(country_ids))
        if self.game_state.active_player != HL:
            return NeutralEntryDecision(
                is_neutral_entry=True,
                country_id=country_id,
                blocked_message="Whitestone player cannot invade neutral countries.",
                invasion_units=invasion_units,
            )

        return NeutralEntryDecision(
            is_neutral_entry=True,
            country_id=country_id,
            confirmation_prompt=f"Invade {country_id}?",
            invasion_units=invasion_units,
        )

    def _eligible_extra_units(self, extra_units, target_hexes):
        """Caller-supplied units that may join the invasion force.

        A unit is eligible when it is a control unit and can either reach a country
        hex on its own or be landed there from its transport.
        """
        eligible = []
        seen = set()
        for unit in (extra_units or []):
            if unit is None or id(unit) in seen:
                continue
            if getattr(unit, "invaded_this_turn", False):
                continue
            if not unit.is_control_unit():
                continue
            if not self._can_extra_unit_invade_target(unit, target_hexes):
                continue
            eligible.append(unit)
            seen.add(id(unit))
        return eligible

    @staticmethod
    def _merge_distinct_units(base_units, extra_units):
        """Concatenate two unit lists, dropping duplicates by object identity."""
        merged = list(base_units or [])
        seen = {id(u) for u in merged}
        for unit in list(extra_units or []):
            if unit is None or id(unit) in seen:
                continue
            merged.append(unit)
            seen.add(id(unit))
        return merged

    def _can_extra_unit_invade_target(self, unit, target_hexes):
        """Can a caller-supplied unit reach the country on its own or by landing?"""
        carrier = getattr(unit, "transport_host", None)
        if carrier is None:
            # On foot: already inside the country, or able to walk into it.
            if not unit.position or None in unit.position:
                return False
            pos = tuple(unit.position)
            if pos in target_hexes:
                return True
            start_hex = Hex.offset_to_axial(pos[0], pos[1])
            return self.movement_service._unit_can_reach_country(unit, start_hex, target_hexes)
        # Embarked: the transport must be in a country hex the unit can land on.
        if not carrier.position or None in carrier.position:
            return False
        landing_hex = Hex.offset_to_axial(*carrier.position)
        if landing_hex.axial_to_offset() not in target_hexes:
            return False
        if not self.game_state.map.can_unit_land_on_hex(unit, landing_hex):
            return False
        return self.game_state.map.can_stack_move_to([unit], landing_hex)

    def _collect_unboard_landing_units(self, selected_units):
        """Map country_id -> units that would land there if the selection unboards."""
        landing = {}
        for unit in selected_units or []:
            carrier = unit.transport_host
            if carrier is None:
                # A transport: its passengers would be unboarded.
                passengers = list(getattr(unit, "passengers", []) or [])
                if not passengers:
                    continue
                for passenger in passengers:
                    self._append_landing_unit(landing, passenger, unit)
                continue
            # A passenger: it would be unboarded from its carrier.
            self._append_landing_unit(landing, unit, carrier)
        return landing

    def _append_landing_unit(self, landing, passenger, carrier):
        """Register ``passenger`` as landing in the country under ``carrier``'s hex."""
        if not carrier or not carrier.position:
            return
        if passenger.allegiance != self.game_state.active_player:
            return
        carrier_hex = Hex.offset_to_axial(*carrier.position)
        col, row = carrier_hex.axial_to_offset()
        country = self.game_state.get_country_by_hex(col, row)
        country_id = country.id if country else None
        landing.setdefault(country_id, []).append(passenger)
