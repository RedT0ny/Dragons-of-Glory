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
        country = self.game_state.countries.get(country_id)
        if not country or country.allegiance != NEUTRAL:
            return {
                "strength": 0,
                "units": [],
                "border_hexes": set(),
                "connected_hexes": set(),
                "reason": "Country is not neutral."
            }

        target_hexes = set(country.territories)
        if not target_hexes:
            return {
                "strength": 0,
                "units": [],
                "border_hexes": set(),
                "connected_hexes": set(),
                "reason": "Country has no territory."
            }

        extra_eligible = self._merge_extra_invasion_units([], extra_units, target_hexes)
        stacks_by_hex = self._hl_stacks_with_passengers()
        if not stacks_by_hex:
            if extra_eligible:
                return {
                    "strength": self._invasion_strength(extra_eligible),
                    "units": extra_eligible,
                    "border_hexes": set(),
                    "connected_hexes": set(),
                    "reason": None,
                }
            return {
                "strength": 0,
                "units": [],
                "border_hexes": set(),
                "connected_hexes": set(),
                "reason": "No Highlord stacks available."
            }

        border_hexes = self._border_stacks_that_can_invade(stacks_by_hex, target_hexes)

        if not border_hexes:
            if extra_eligible:
                return {
                    "strength": self._invasion_strength(extra_eligible),
                    "units": extra_eligible,
                    "border_hexes": set(),
                    "connected_hexes": set(),
                    "reason": None,
                }
            return {
                "strength": 0,
                "units": [],
                "border_hexes": set(),
                "connected_hexes": set(),
                "reason": "No eligible Highlord stacks adjacent to the border."
            }

        connected_hexes = self._connected_support_hexes(border_hexes, stacks_by_hex.keys())
        eligible_units = self._invasion_units_from_connected_hexes(connected_hexes, stacks_by_hex)
        eligible_units = self._merge_distinct_units(eligible_units, extra_eligible)
        strength = self._invasion_strength(eligible_units)

        return {
            "strength": strength,
            "units": eligible_units,
            "border_hexes": border_hexes,
            "connected_hexes": connected_hexes,
            "reason": None
        }

    @staticmethod
    def _invasion_strength(units):
        """Calculate invasion strength based on units. Dragons count triple."""
        total = 0
        for unit in list(units or []):
            rating = int(unit.combat_rating)
            if rating <= 0:
                continue
            if getattr(unit, "is_dragon", lambda: False)():
                total += rating * 3
            else:
                total += rating
        return total

    def _hl_stacks_with_passengers(self):
        """Collect all Highlord stacks on the map, including passengers."""
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

    def _border_stacks_that_can_invade(self, stacks_by_hex, target_hexes):
        border_hexes = set()
        for hex_obj, stack_units in stacks_by_hex.items():
            if not any(neighbor.axial_to_offset() in target_hexes for neighbor in hex_obj.neighbors()):
                continue
            if self._stack_can_invade_from_hex(hex_obj, stack_units, target_hexes):
                border_hexes.add(hex_obj)
        return border_hexes

    def _stack_can_invade_from_hex(self, hex_obj, stack_units, target_hexes) -> bool:
        combat_units = [u for u in stack_units if not u.is_fleet()]
        if not combat_units:
            return False
        for neighbor in hex_obj.neighbors():
            if neighbor.axial_to_offset() not in target_hexes:
                continue
            if not self.game_state.map.can_stack_move_to(combat_units, neighbor):
                continue
            if any(self.movement_service._unit_can_enter_hex(unit, hex_obj, neighbor) for unit in combat_units):
                return True
        return False

    @staticmethod
    def _connected_support_hexes(border_hexes, all_stack_hexes) -> set[Hex]:
        remaining = set(all_stack_hexes)
        connected = set(border_hexes)
        frontier = list(border_hexes)
        for hex_obj in border_hexes:
            remaining.discard(hex_obj)
        while frontier:
            current = frontier.pop()
            for neighbor in current.neighbors():
                if neighbor not in remaining:
                    continue
                remaining.remove(neighbor)
                connected.add(neighbor)
                frontier.append(neighbor)
        return connected

    def _invasion_units_from_connected_hexes(self, connected_hexes, stacks_by_hex) -> list[Unit]:
        eligible = []
        for hex_obj in connected_hexes:
            for unit in stacks_by_hex.get(hex_obj, []):
                if unit.is_fleet():
                    continue
                eligible.append(unit)
        return eligible

    def evaluate_unboard_neutral_entry(self, selected_units) -> NeutralEntryDecision:
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

    def _merge_extra_invasion_units(self, base_units, extra_units, target_hexes):
        merged = list(base_units or [])
        seen = {id(u) for u in merged}
        for unit in list(extra_units or []):
            if unit is None or id(unit) in seen:
                continue
            if unit.allegiance != HL:
                continue
            if unit.is_fleet():
                continue
            if not self._can_extra_unit_invade_target(unit, target_hexes):
                continue
            merged.append(unit)
            seen.add(id(unit))
        return merged

    @staticmethod
    def _merge_distinct_units(base_units, extra_units):
        merged = list(base_units or [])
        seen = {id(u) for u in merged}
        for unit in list(extra_units or []):
            if unit is None or id(unit) in seen:
                continue
            merged.append(unit)
            seen.add(id(unit))
        return merged

    def _can_extra_unit_invade_target(self, unit, target_hexes):
        carrier = getattr(unit, "transport_host", None)
        if carrier is None:
            if not unit.position or None in unit.position:
                return False
            pos = tuple(unit.position)
            if pos in target_hexes:
                return True
            start_hex = Hex.offset_to_axial(pos[0], pos[1])
            return self.movement_service._unit_can_reach_country(unit, start_hex, target_hexes)
        if not carrier.position or None in carrier.position:
            return False
        landing_hex = Hex.offset_to_axial(*carrier.position)
        if landing_hex.axial_to_offset() not in target_hexes:
            return False
        if not self.game_state.map.can_unit_land_on_hex(unit, landing_hex):
            return False
        return self.game_state.map.can_stack_move_to([unit], landing_hex)

    def _collect_unboard_landing_units(self, selected_units):
        landing = {}
        for unit in selected_units or []:
            carrier = unit.transport_host
            if carrier is None:
                passengers = list(getattr(unit, "passengers", []) or [])
                if not passengers:
                    continue
                for passenger in passengers:
                    self._append_landing_unit(landing, passenger, unit)
                continue
            self._append_landing_unit(landing, unit, carrier)
        return landing

    def _append_landing_unit(self, landing, passenger, carrier):
        if not carrier or not carrier.position:
            return
        if passenger.allegiance != self.game_state.active_player:
            return
        carrier_hex = Hex.offset_to_axial(*carrier.position)
        col, row = carrier_hex.axial_to_offset()
        country = self.game_state.get_country_by_hex(col, row)
        country_id = country.id if country else None
        landing.setdefault(country_id, []).append(passenger)
