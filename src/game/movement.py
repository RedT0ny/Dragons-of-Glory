"""
Movement module for Dragons of Glory.

This module handles unit movement, interception, boarding/unboarding, and related game logic.
It includes pathfinding, cost calculations, and special rules for fleets, wings, and armies.
"""

from dataclasses import dataclass
from collections import defaultdict
import random
from typing import List, Tuple

from shiboken6.Shiboken import Object

from content.tools import TextFormatter, debug_print
from game.unit import Unit
from src.content.constants import HL, NEUTRAL, WS
from src.content.specs import GamePhase, LocType, UnitType
from src.game.interception import InterceptionService
from src.game.map import Hex, Hexside

_KEEP_FIELD = object()


@dataclass
class BoardActionResult:
    """Result of a boarding/unboarding action."""
    handled: bool
    messages: List[str]
    force_sync: bool


@dataclass
class MovementRangeResult:
    """Result containing reachable hexes and neutral warnings for UI."""
    reachable_coords: List[Tuple[int, int]]
    neutral_warning_coords: List[Tuple[int, int]]

@dataclass
class MoveUnitsResult:
    """Result of moving units to a hex."""
    moved: List[object]
    errors: List[str]


@dataclass
class MoveEvaluation:
    ok: bool
    reason: str | None
    cost: int
    start_hex: Hex | None
    path_hexes: List[Hex]
    fleet_state_path: List[Tuple[Hex, Hexside | None]]
    final_river_hexside: Hexside | None


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
        """
        Calculate invasion strength based on units. Dragons count triple.
        """
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
        """
        Collect all Highlord stacks on the map, including passengers, for invasion consideration.
        """
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
        """
        Identify stacks that are adjacent to the target country and have at least one unit capable of invading
        into the target hexes.
        """
        border_hexes = set()
        for hex_obj, stack_units in stacks_by_hex.items():
            if not any(neighbor.axial_to_offset() in target_hexes for neighbor in hex_obj.neighbors()):
                continue
            if self._stack_can_invade_from_hex(hex_obj, stack_units, target_hexes):
                border_hexes.add(hex_obj)
        return border_hexes

    def _stack_can_invade_from_hex(self, hex_obj, stack_units, target_hexes) -> bool:
        """
        Determine if any unit in the stack can invade into the target hexes from the given hex.
         Fleets cannot invade, so only consider combat units.
         A unit can invade if it can enter at least one of the target hexes from the current hex.
         This checks movement rules, terrain, and any special conditions for invasion.
        """
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
        """
        Perform a flood-fill from the border hexes to find all connected hexes that contain Highlord stacks.
        """
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
        """
        From the connected hexes, collect all units that are eligible to participate in the invasion.
        """
        eligible = []
        for hex_obj in connected_hexes:
            for unit in stacks_by_hex.get(hex_obj, []):
                if unit.is_fleet():
                    continue
                if not self.movement_service._unit_has_movement(unit):
                    continue
                eligible.append(unit)
        return eligible

    def evaluate_unboard_neutral_entry(self, selected_units) -> NeutralEntryDecision:
        """
        Evaluate if unboarding the selected units would result in entering a neutral country, and if so, determine the
        implications.
         This checks the landing hexes of the selected units, identifies any neutral countries they would land in,
         and assesses whether an invasion would occur.
         If multiple neutral countries are involved, it blocks the action. If a single neutral country is involved, it
         provides details for confirmation or blocking based on the active player.
         The decision includes whether it's a neutral entry, which country is involved, any blocking messages,
         confirmation prompts, and which units would be part of the invasion force.
         This logic is used to ensure that players are aware of and confirm any actions that would lead to invading
          neutral territory through unboarding.
         It also integrates with the invasion evaluation logic to determine the strength and composition of the invasion
          force if applicable.
         The method returns a NeutralEntryDecision object that encapsulates all relevant information for handling this
          scenario in the UI and game flow.
        """
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
        """
        Merge extra units into the base invasion force, ensuring they are eligible to invade the target hexes.
        """
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
        """
        Merge two lists of units, ensuring no duplicates based on object identity.
         This is used to combine units from different sources (e.g., border stacks and extra units) while avoiding duplicates.
         The method iterates through the extra_units and adds them to the merged list only if they are not already present
          in base_units, as determined by their id() value.
         The order of units is preserved, with base_units appearing first followed by any unique extra_units.
        """
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


class MovementService:
    """Handles all movement-related logic, including pathfinding, interception, boarding, and neutral entry."""
    def __init__(self, game_state):
        self.game_state = game_state
        self.interception_service = InterceptionService(game_state, self, rng=random)
        self._movement_undo_stack = []
        self.invasion_handler = InvasionHandler(self)

    def _effective_mp(self, unit):
        current = getattr(unit, "movement_points", unit.movement)
        return min(current, unit.movement)

    @staticmethod
    def _fleet_hex_path_from_state_path(state_path):
        if not state_path:
            return []
        hex_path = []
        prev_hex = state_path[0][0]
        for curr_hex, _ in state_path[1:]:
            if curr_hex != prev_hex:
                hex_path.append(curr_hex)
            prev_hex = curr_hex
        return hex_path

    def _format_river_hexside_for_log(self, river_hexside):
        master = self.game_state.map.hexside_to_tuple(river_hexside)
        if master is None:
            return "None"
        board = self.game_state.map
        try:
            local_a = board._local_hex_from_master_coords(master[0][0], master[0][1]).axial_to_offset()
            local_b = board._local_hex_from_master_coords(master[1][0], master[1][1]).axial_to_offset()
            return f"{local_a}<->{local_b}"
        except Exception:
            return "Unknown"

    def _log_fleet_transition(self, unit, prev_hex, prev_side, curr_hex, curr_side):
        unit_id = TextFormatter.format_unit_log_string(unit)
        prev_hex_offset = prev_hex.axial_to_offset()
        curr_hex_offset = curr_hex.axial_to_offset()
        prev_side_text = self._format_river_hexside_for_log(prev_side)
        curr_side_text = self._format_river_hexside_for_log(curr_side)

        if prev_side is None and curr_side is None and prev_hex != curr_hex:
            debug_print(f"{unit_id} sails sea/coastal hex {prev_hex_offset} -> {curr_hex_offset}.")
            return

        if prev_side is None and curr_side is not None:
            debug_print(
                f"{unit_id} enters deep_river hexside {curr_side_text} from hex {prev_hex_offset} "
                f"(now at endpoint {curr_hex_offset})."
            )
            return

        if prev_side is not None and curr_side is None:
            debug_print(
                f"{unit_id} exits deep_river hexside {prev_side_text} to hex {curr_hex_offset} "
                f"(from endpoint {prev_hex_offset})."
            )
            return

        if prev_side is not None and curr_side == prev_side and prev_hex != curr_hex:
            debug_print(f"{unit_id} shifts along deep_river endpoint {prev_hex_offset} -> {curr_hex_offset} on {curr_side_text}.")
            return

        if prev_side is not None and curr_side != prev_side:
            debug_print(
                f"{unit_id} changes deep_river hexside {prev_side_text} -> {curr_side_text} "
                f"at/near endpoint {curr_hex_offset}."
            )
            return

        if prev_side == curr_side and prev_hex == curr_hex:
            debug_print(f"{unit_id} remains at hex {curr_hex_offset} (hexside={curr_side}).")

    def evaluate_move(self, unit, target_hex, enforce_end_terrain: bool = True) -> MoveEvaluation:
        unit_id = TextFormatter.format_unit_log_string(unit)
        if getattr(unit, "transport_host", None) is not None:
            return MoveEvaluation(False, f"{unit_id} is transported and cannot move independently.", 0, None, [], [], None)

        if enforce_end_terrain and not unit.is_fleet() and not self.game_state.map.can_unit_land_on_hex(unit, target_hex):
            tcol, trow = target_hex.axial_to_offset()
            terrain = self.game_state.map.get_terrain(target_hex)
            return MoveEvaluation(
                False,
                f"{unit_id} cannot end movement on that terrain (target={tcol},{trow} terrain={getattr(terrain, 'value', terrain)}).",
                0,
                None,
                [],
                [],
                None,
            )

        if not unit.position or None in unit.position:
            return MoveEvaluation(True, None, 0, None, [], [], None)

        max_mp = self._effective_mp(unit)
        start_hex = Hex.offset_to_axial(*unit.position)
        if unit.is_fleet():
            state_path, cost = self.game_state.map.find_fleet_route(unit, start_hex, target_hex)
            if cost == float("inf") or (not state_path and start_hex != target_hex):
                return MoveEvaluation(False, f"{unit_id} has no valid path.", 0, start_hex, [], [], None)
            final_river_hexside = state_path[-1][1] if state_path else getattr(unit, "river_hexside", None)
            path_hexes = self._fleet_hex_path_from_state_path(state_path)
            if cost > max_mp:
                return MoveEvaluation(False, f"{unit_id} lacks movement points.", cost, start_hex, path_hexes, state_path, final_river_hexside)
            return MoveEvaluation(True, None, cost, start_hex, path_hexes, state_path, final_river_hexside)

        path = self.game_state.map.find_shortest_path(unit, start_hex, target_hex)
        if not path and start_hex != target_hex:
            return MoveEvaluation(False, f"{unit_id} has no valid path.", 0, start_hex, [], [], None)

        cost = 0
        current = start_hex
        for next_step in path:
            step_cost = self.game_state.map.get_movement_cost(unit, current, next_step)
            cost += step_cost
            current = next_step

        if cost > max_mp:
            return MoveEvaluation(False, f"{unit_id} lacks movement points.", cost, start_hex, path, [], None)

        return MoveEvaluation(True, None, cost, start_hex, path, [], None)

    def execute_move(self, unit, target_hex, evaluation: MoveEvaluation, enforce_end_terrain: bool = True):
        if not evaluation.ok:
            return False
        if enforce_end_terrain:
            follow_up = self.evaluate_move(unit, target_hex, enforce_end_terrain=True)
            if not follow_up.ok:
                return False
            evaluation = follow_up

        if self.game_state.phase == GamePhase.MOVEMENT and unit.position:
            if not hasattr(unit, "movement_points"):
                unit.movement_points = unit.movement
            effective_mp = self._effective_mp(unit)
            if evaluation.cost > effective_mp:
                return False
            unit.movement_points = max(0, effective_mp - evaluation.cost)

        kwargs = {
            "invalidate_analysis": False,
            "update_territory": False,
            "invalidate_overlays": False,
            "enforce_end_terrain": enforce_end_terrain,
        }
        if self.game_state.phase == GamePhase.MOVEMENT and unit.is_fleet():
            kwargs["river_hexside"] = evaluation.final_river_hexside
        self.game_state.move_unit(unit, target_hex, **kwargs)
        if unit.is_fleet() and evaluation.fleet_state_path:
            for i in range(1, len(evaluation.fleet_state_path)):
                prev_hex, prev_side = evaluation.fleet_state_path[i - 1]
                curr_hex, curr_side = evaluation.fleet_state_path[i]
                self._log_fleet_transition(unit, prev_hex, prev_side, curr_hex, curr_side)
        return getattr(unit, "position", None) == target_hex.axial_to_offset() or not getattr(unit, "is_on_map", False)

    # --- Movement Undo State ---
    def clear_movement_undo(self):
        self._movement_undo_stack.clear()

    def can_undo_movement(self):
        return bool(self._movement_undo_stack)

    def push_movement_undo_snapshot(self):
        unit_states = []
        for unit in self.game_state.units:
            unit_states.append({
                "unit": unit,
                "position": tuple(unit.position),
                "status": unit.status,
                "movement_points": unit.movement_points,
                "moved_this_turn": unit.moved_this_turn,
                "attacked_this_turn": unit.attacked_this_turn,
                "is_transported": unit.is_transported,
                "transport_host": unit.transport_host,
                "river_hexside": getattr(unit, "river_hexside", None),
                "passengers": list(getattr(unit, "passengers", [])),
                "escaped": bool(getattr(unit, "escaped", False)),
            })
        self._movement_undo_stack.append({
            "turn": self.game_state.turn,
            "active_player": self.game_state.active_player,
            "units": unit_states,
            "territory_overrides": dict(self.game_state.territory_overrides or {}),
        })

    def discard_last_movement_snapshot(self):
        if self._movement_undo_stack:
            self._movement_undo_stack.pop()

    # --- Unified Mutation Path ---
    def relocate_unit_on_board(
        self,
        unit,
        target_hex,
        *,
        river_hexside=_KEEP_FIELD,
        clear_escaped: bool = True,
    ) -> bool:
        """Single path for on-board relocation + spatial-map + passenger synchronization."""
        if unit is None or target_hex is None:
            return False

        self.game_state.map.remove_unit_from_spatial_map(unit)
        unit.position = target_hex.axial_to_offset()
        if clear_escaped and hasattr(unit, "escaped"):
            unit.escaped = False
        if river_hexside is not _KEEP_FIELD and hasattr(unit, "river_hexside"):
            unit.river_hexside = river_hexside
        self.game_state.map.add_unit_to_spatial_map(unit)
        self._sync_carrier_passengers(unit)
        return True

    def remove_unit_from_board(
        self,
        unit,
        *,
        escaped: bool = False,
        clear_transport: bool = True,
        clear_river_hexside: bool = False,
        remove_passengers: bool = False,
    ) -> bool:
        """Single path for removing a unit from the board and spatial-map state."""
        if unit is None:
            return False

        passenger_list = list(getattr(unit, "passengers", []) or []) if remove_passengers else []
        self.game_state.map.remove_unit_from_spatial_map(unit)
        unit.position = (None, None)
        if hasattr(unit, "escaped"):
            unit.escaped = bool(escaped)
        if clear_transport:
            self._detach_unit_from_carriers(unit)
            unit.is_transported = False
            unit.transport_host = None
        if clear_river_hexside and hasattr(unit, "river_hexside"):
            unit.river_hexside = None

        if remove_passengers and hasattr(unit, "passengers"):
            unit.passengers = []
            for passenger in passenger_list:
                self.remove_unit_from_board(
                    passenger,
                    escaped=escaped,
                    clear_transport=True,
                    clear_river_hexside=False,
                    remove_passengers=False,
                )
        return True

    def _sync_carrier_passengers(self, carrier):
        passengers = getattr(carrier, "passengers", None)
        if not passengers:
            return
        for passenger in passengers:
            passenger.position = carrier.position
            passenger.is_transported = True
            passenger.transport_host = carrier

    def _detach_unit_from_carriers(self, unit):
        host = getattr(unit, "transport_host", None)
        if host is not None and hasattr(host, "passengers"):
            while unit in host.passengers:
                host.passengers.remove(unit)
        for maybe_carrier in self.game_state.units:
            if maybe_carrier is host:
                continue
            passengers = getattr(maybe_carrier, "passengers", None)
            if not passengers or unit not in passengers:
                continue
            while unit in passengers:
                passengers.remove(unit)

    def undo_last_movement(self):
        if not self._movement_undo_stack:
            return False

        snapshot = self._movement_undo_stack.pop()
        if snapshot["turn"] != self.game_state.turn or snapshot["active_player"] != self.game_state.active_player:
            self._movement_undo_stack.clear()
            return False

        for state in snapshot["units"]:
            unit = state["unit"]
            unit.position = state["position"]
            unit.status = state["status"]
            if state["movement_points"] is not None:
                unit.movement_points = state["movement_points"]
            unit.moved_this_turn = state["moved_this_turn"]
            unit.attacked_this_turn = state["attacked_this_turn"]
            unit.is_transported = state["is_transported"]
            unit.transport_host = state["transport_host"]
            if hasattr(unit, "river_hexside"):
                unit.river_hexside = state["river_hexside"]
            if hasattr(unit, "passengers"):
                unit.passengers = list(state["passengers"])
            unit.escaped = bool(state.get("escaped", False))

        self.game_state.map.unit_map = defaultdict(list)
        for unit in self.game_state.units:
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None or pos[1] is None:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            self.game_state.map.add_unit_to_spatial_map(unit)

        self.game_state.territory_overrides = dict(snapshot.get("territory_overrides", {}) or {})
        self.game_state.invalidate_analysis({"control_facts"})
        self.game_state.invalidate_overlays({"control", "territory", "supply", "ws_power", "hl_power", "threat"})
        return True

    # --- Transport State ---
    def board_unit(self, carrier, unit):
        if getattr(carrier, "moved_this_turn", False) or getattr(unit, "moved_this_turn", False):
            return False

        if not carrier.can_carry(unit):
            return False

        if not carrier.position or not unit.position or carrier.position != unit.position:
            return False

        self.game_state.map.remove_unit_from_spatial_map(unit)
        carrier.load_unit(unit)
        unit.position = carrier.position
        unit.is_transported = True
        if hasattr(unit, "movement_points"):
            unit.movement_points = 0
        unit.moved_this_turn = True
        unit.transport_host = carrier

        if carrier.is_fleet():
            in_port = False
            if carrier.position:
                hex_obj = Hex.offset_to_axial(*carrier.position)
                loc = self.game_state.map.get_location(hex_obj)
                in_port = bool(loc and loc.loc_type == LocType.PORT.value)
            if not in_port and hasattr(carrier, "movement_points"):
                carrier.movement_points = min(
                    carrier.movement_points,
                    max(0, int(carrier.movement // 2)),
                )
        if hasattr(carrier, "movement_points"):
            carrier.movement_points = min(carrier.movement_points, carrier.movement)

        self.normalize_transport_state()
        return True

    def can_unboard_unit_to_hex(self, unit, dest_hex) -> bool:
        carrier = getattr(unit, 'transport_host', None)
        if not carrier:
            return False

        if dest_hex is None and carrier.position:
            dest_hex = Hex.offset_to_axial(*carrier.position)
        if dest_hex is None:
            return False

        if carrier.is_fleet():
            loc = self.game_state.map.get_location(dest_hex)
            is_stateless_neutral_port = bool(
                loc
                and getattr(loc, "loc_type", None) == LocType.PORT.value
                and getattr(loc, "country_id", None) is None
                and getattr(loc, "occupier", None) == NEUTRAL
            )
            col, row = dest_hex.axial_to_offset()
            country = self.game_state.get_country_by_hex(col, row)
            if country and country.allegiance == NEUTRAL and not is_stateless_neutral_port:
                return False

        if not self.game_state.map.can_unit_land_on_hex(unit, dest_hex):
            return False

        if not self.game_state.map.can_stack_move_to([unit], dest_hex):
            return False
        return True

    def get_valid_unboard_hexes(self, carrier, passenger=None) -> List[Hex]:
        if not carrier or not getattr(carrier, "position", None) or carrier.position[0] is None:
            return []

        carrier_hex = Hex.offset_to_axial(*carrier.position)
        candidates = [carrier_hex]
        if carrier.is_fleet():
            candidates.extend(carrier_hex.neighbors())

        passengers = [passenger] if passenger is not None else list(getattr(carrier, "passengers", []) or [])
        if not passengers:
            return []

        valid: List[Hex] = []
        seen = set()
        for h in candidates:
            if (h.q, h.r) in seen:
                continue
            seen.add((h.q, h.r))
            if any(self.can_unboard_unit_to_hex(p, h) for p in passengers):
                valid.append(h)
        return valid

    def unboard_unit(self, unit, target_hex=None):
        carrier = getattr(unit, 'transport_host', None)
        if not carrier:
            return False

        dest_hex = target_hex
        if dest_hex is None and carrier.position:
            dest_hex = Hex.offset_to_axial(*carrier.position)
        if not self.can_unboard_unit_to_hex(unit, dest_hex):
            return False

        self._detach_unit_from_carriers(unit)
        unit.transport_host = None
        unit.is_transported = False
        if hasattr(unit, "movement_points"):
            unit.movement_points = 0
        unit.moved_this_turn = True
        self.relocate_unit_on_board(unit, dest_hex, clear_escaped=False)
        self.game_state.finalize_board_state_change()
        if carrier.is_wing():
            if hasattr(carrier, "movement_points"):
                carrier.movement_points = 0
            carrier.moved_this_turn = True
        elif carrier.is_fleet():
            in_port = False
            if carrier.position:
                loc = self.game_state.map.get_location(Hex.offset_to_axial(*carrier.position))
                in_port = bool(loc and loc.loc_type == LocType.PORT.value)
            if not in_port:
                if hasattr(carrier, "movement_points"):
                    carrier.movement_points = 0
                carrier.moved_this_turn = True
        self.normalize_transport_state()
        return True

    def normalize_transport_state(self):
        if not self.game_state.units:
            return

        carriers = [u for u in self.game_state.units if hasattr(u, "passengers")]
        passenger_owner = {}

        for carrier in carriers:
            raw = list(getattr(carrier, "passengers", []) or [])
            cleaned = []
            seen = set()
            for passenger in raw:
                if passenger is None or passenger is carrier:
                    continue
                marker = id(passenger)
                if marker in seen:
                    continue
                if marker in passenger_owner:
                    continue
                seen.add(marker)
                passenger_owner[marker] = carrier
                cleaned.append(passenger)
            carrier.passengers = cleaned

        for unit in self.game_state.units:
            host = getattr(unit, "transport_host", None)
            if host is None:
                continue
            if not hasattr(host, "passengers"):
                unit.transport_host = None
                unit.is_transported = False
                continue
            if unit not in host.passengers:
                host.passengers.append(unit)
            unit.is_transported = True
            if host.position and host.position != (None, None):
                unit.position = host.position
            self.game_state.map.remove_unit_from_spatial_map(unit)

        for carrier in carriers:
            valid = []
            seen = set()
            for passenger in carrier.passengers:
                if getattr(passenger, "transport_host", None) is not carrier:
                    continue
                marker = id(passenger)
                if marker in seen:
                    continue
                seen.add(marker)
                valid.append(passenger)
            carrier.passengers = valid

    def get_reachable_hexes(self, units):
        """
        Returns reachable hexes plus neutral-border warnings for UI highlighting.
        """
        if not units:
            return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])
        if all(u.is_fleet() for u in units):
            start_hex, _ = self.game_state.map.get_stack_start_and_min_mp(units)
            if not start_hex:
                return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])
            most_restrictive_fleet = min(units, key=self._effective_mp)
            return self._range_result_from_hexes(
                self.game_state.map.get_reachable_hexes_for_fleet(most_restrictive_fleet)
            )

        start_hex, _ = self.game_state.map.get_stack_start_and_min_mp(units)
        if not start_hex:
            return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])

        if self._is_neutral_hex(start_hex):
            return self._range_result_from_hexes(self.game_state.map.get_reachable_hexes(units))

        reachable, warnings = self.game_state.map.get_reachable_hexes(
            units,
            stop_on_neutral=True,
            neutral_predicate=self._is_neutral_hex,
            split_neutral=True,
        )
        return MovementRangeResult(
            reachable_coords=[h.axial_to_offset() for h in reachable],
            neutral_warning_coords=[h.axial_to_offset() for h in warnings],
        )

    @staticmethod
    def _range_result_from_hexes(reachable_hexes):
        return MovementRangeResult(
            reachable_coords=[h.axial_to_offset() for h in reachable_hexes],
            neutral_warning_coords=[],
        )

    def move_units_to_hex(self, units, target_hex):
        if not units:
            return MoveUnitsResult(moved=[], errors=[])
        # Defensive de-duplication in case the UI passes duplicate selections.
        deduped = []
        seen_ids = set()
        for unit in units:
            marker = id(unit)
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            deduped.append(unit)
        units = deduped

        # Mixed stacks that include ground armies can legally enter enemy-fleet hexes.
        # Validate these as a stack, not unit-by-unit, to avoid false "no valid path".
        if len(units) > 1 and any(u.is_army() for u in units):
            ok, reason = self._can_stack_reach_target(units, target_hex)
            if not ok:
                return MoveUnitsResult(moved=[], errors=[reason or "Selected stack cannot move there."])

            ordered_units = sorted(units, key=lambda u: 0 if u.is_army() else 1)
            return self._execute_unit_move_batch(ordered_units, target_hex)

        if self.interception_service.should_check_interception(units):
            return self._move_units_with_interception(units, target_hex)

        errors = []
        for unit in units:
            ok, reason = self._can_unit_reach_target(unit, target_hex)
            if not ok:
                errors.append(reason or f"{TextFormatter.format_unit_log_string(unit)} cannot move.")

        if errors:
            return MoveUnitsResult(moved=[], errors=errors)

        return self._execute_unit_move_batch(units, target_hex)

    def _execute_unit_move_batch(self, units, target_hex) -> MoveUnitsResult:
        moved = []
        for unit in units:
            evaluation = self.evaluate_move(unit, target_hex)
            if not evaluation.ok:
                message = evaluation.reason or f"{TextFormatter.format_unit_log_string(unit)} cannot move."
                return MoveUnitsResult(moved=moved, errors=[message])
            if not self.execute_move(unit, target_hex, evaluation):
                message = evaluation.reason or f"{TextFormatter.format_unit_log_string(unit)} cannot move."
                return MoveUnitsResult(moved=moved, errors=[message])
            moved.append(unit)
        if moved:
            self.game_state.finalize_board_state_change()
        return MoveUnitsResult(moved=moved, errors=[])

    def _move_units_with_interception(self, units, target_hex):
        lead = units[0]
        evaluations = {}
        lead_evaluation = None
        for unit in units:
            evaluation = self.evaluate_move(unit, target_hex)
            evaluations[id(unit)] = evaluation
            if not evaluation.ok:
                return MoveUnitsResult(moved=[], errors=[evaluation.reason or f"{TextFormatter.format_unit_log_string(unit)} cannot move."])
            if unit is lead:
                lead_evaluation = evaluation

        path = self._build_movement_hex_path(
            units,
            target_hex,
            precomputed_evaluation=lead_evaluation,
        )
        if path is None:
            return MoveUnitsResult(moved=[], errors=["Selected stack has no valid path."])
        if not path:
            return MoveUnitsResult(moved=list(units), errors=[])

        moving_units = [u for u in units if getattr(u, "is_on_map", False)]
        for unit in moving_units:
            evaluation = evaluations[id(unit)]
            if self.game_state.phase == GamePhase.MOVEMENT and getattr(unit, "position", None):
                if not hasattr(unit, "movement_points"):
                    unit.movement_points = unit.movement
                effective_mp = self._effective_mp(unit)
                if evaluation.cost > effective_mp:
                    return MoveUnitsResult(moved=[], errors=[evaluation.reason or f"{TextFormatter.format_unit_log_string(unit)} lacks movement points."])
                unit.movement_points = max(0, effective_mp - evaluation.cost)

        for idx, step_hex in enumerate(path):
            is_final_step = idx == (len(path) - 1)
            for unit in list(units):
                if not getattr(unit, "is_on_map", False):
                    continue
                prev_hex = None
                prev_side = None
                if unit.is_fleet() and getattr(unit, "position", None) and None not in unit.position:
                    prev_hex = Hex.offset_to_axial(*unit.position)
                    prev_side = getattr(unit, "river_hexside", None)
                kwargs = {
                    "invalidate_analysis": False,
                    "update_territory": False,
                    "invalidate_overlays": False,
                    "enforce_end_terrain": is_final_step,
                }
                if self.game_state.phase == GamePhase.MOVEMENT and unit.is_fleet() and is_final_step:
                    kwargs["river_hexside"] = evaluations[id(unit)].final_river_hexside
                self.game_state.move_unit(unit, step_hex, **kwargs)
                if unit.is_fleet() and prev_hex is not None and getattr(unit, "position", None) and None not in unit.position:
                    curr_hex = Hex.offset_to_axial(*unit.position)
                    curr_side = getattr(unit, "river_hexside", None)
                    self._log_fleet_transition(unit, prev_hex, prev_side, curr_hex, curr_side)
                if getattr(unit, "is_on_map", False) and getattr(unit, "position", None) != step_hex.axial_to_offset():
                    message = f"{TextFormatter.format_unit_log_string(unit)} cannot move."
                    return MoveUnitsResult(moved=[], errors=[message])

            movers_alive = [u for u in units if u.is_on_map]
            if not movers_alive:
                return MoveUnitsResult(moved=[], errors=[])

            intercepted = self.interception_service.maybe_apply_interception(movers_alive, step_hex)
            movers_alive = [u for u in units if u.is_on_map]
            if not movers_alive:
                return MoveUnitsResult(moved=[], errors=[])

            if intercepted:
                print(f"Interception resolved at {step_hex.axial_to_offset()}.")

        self.game_state.finalize_board_state_change()
        return MoveUnitsResult(moved=[u for u in units if u.is_on_map], errors=[])

    def _build_movement_hex_path(self, units, target_hex, precomputed_evaluation=None):
        """
        Builds a hex path for a group of units to move to a target hex.
        Returns a list of hex coordinates or None if the path cannot be computed.
        """
        lead = units[0]
        if not getattr(lead, "position", None) or lead.position[0] is None or lead.position[1] is None:
            return []
        start_hex = Hex.offset_to_axial(*lead.position)
        if start_hex == target_hex:
            return []

        if lead.is_fleet():
            state_path = None
            if isinstance(precomputed_evaluation, MoveEvaluation):
                state_path = precomputed_evaluation.fleet_state_path
            if state_path is None:
                evaluation = self.evaluate_move(lead, target_hex)
                if not evaluation.ok:
                    return None
                state_path = evaluation.fleet_state_path
            return self._fleet_hex_path_from_state_path(state_path)

        path = self.game_state.map.find_shortest_path(lead, start_hex, target_hex)
        if not path and start_hex != target_hex:
            return None
        return path

    def _can_stack_reach_target(self, units, target_hex):
        """Checks if a stack of units can reach a target hex, considering movement points and terrain."""
        start_hex, _ = self.game_state.map.get_stack_start_and_min_mp(units)
        if not start_hex:
            return False, "Selected units are not in the same hex."
        if start_hex == target_hex:
            return True, None
        reachable = self.game_state.map.get_reachable_hexes(units)
        if target_hex in reachable:
            return True, None
        return False, "Selected stack has no valid path."

    def _is_neutral_hex(self, hex_obj):
        col, row = hex_obj.axial_to_offset()
        country = self.game_state.get_country_by_hex(col, row)
        return bool(country and country.allegiance == NEUTRAL)

    def get_invasion_force(self, country_id, extra_units=None):
        return self.invasion_handler.get_invasion_force(country_id, extra_units=extra_units)

    def _unit_can_reach_country(self, unit, from_hex, target_hexes):
        return any(
            neighbor.axial_to_offset() in target_hexes and self._unit_can_enter_hex(unit, from_hex, neighbor)
            for neighbor in from_hex.neighbors()
        )

    def _unit_can_enter_hex(self, unit, from_hex, target_hex):
        carrier = getattr(unit, "transport_host", None)
        if carrier is not None:
            if not carrier.position:
                return False
            carrier_hex = Hex.offset_to_axial(*carrier.position)
            if carrier_hex != from_hex:
                return False
            if not self.game_state.map.can_unit_land_on_hex(unit, target_hex):
                return False
            return self.game_state.map.can_stack_move_to([unit], target_hex)

        return self.game_state.map.can_unit_enter_from_hex(
            unit,
            from_hex,
            target_hex,
            available_mp=self._unit_movement_points(unit),
        )

    def _unit_has_movement(self, unit):
        return self._unit_movement_points(unit) > 0

    def _unit_movement_points(self, unit):
        return self._effective_mp(unit)

    def _can_unit_reach_target(self, unit, target_hex):
        evaluation = self.evaluate_move(unit, target_hex)
        return evaluation.ok, evaluation.reason

    def handle_board_action(self, selected_units):
        if not selected_units:
            return BoardActionResult(handled=False, messages=[], force_sync=False)

        messages = []

        # Separate carriers, armies, leaders
        carriers = [u for u in selected_units if u.is_fleet() or getattr(u, 'passengers', None) is not None]
        armies = [u for u in selected_units if u.is_army()]
        leaders = [u for u in selected_units if u.is_leader()]

        # If selection includes transported units, unboard them (only if carrier is in coastal hex)
        transported = [u for u in selected_units if getattr(u, 'transport_host', None) is not None]
        if transported:
            for u in transported:
                carrier = u.transport_host
                if not carrier or not carrier.position:
                    messages.append(f"Cannot unboard {u.id}: carrier missing position")
                    continue
                carrier_hex = Hex.offset_to_axial(*carrier.position)
                if carrier.is_wing():
                    if not self.game_state.map.can_unit_land_on_hex(u, carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: destination terrain invalid for passenger")
                        continue
                elif carrier.is_citadel():
                    if not self.game_state.map.can_unit_land_on_hex(u, carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: destination terrain invalid for passenger")
                        continue
                else:
                    is_coastal = self.game_state.map.is_coastal(carrier_hex)
                    loc = self.game_state.map.get_location(carrier_hex)
                    is_port = bool(loc and loc.loc_type == LocType.PORT.value)
                    if not (is_coastal or is_port):
                        messages.append(f"Cannot unboard {u.id}: carrier not in coastal hex or port")
                        continue
                success = self.unboard_unit(u)
                if not success:
                    messages.append(f"Failed to unboard {u.id} due to stacking or location.")
            return BoardActionResult(handled=True, messages=messages, force_sync=True)

        # Unboarding variant: Because transported units cannot be selected (they're removed from the spatial map),
        # we detect carriers (fleets/wings/citadels) among the selection that have passengers and attempt to
        # unboard their passengers if the carrier is in a coastal hex or in a port.
        carriers_with_passengers = [u for u in selected_units if getattr(u, 'passengers', None) and len(u.passengers) > 0]
        if carriers_with_passengers:
            for carrier in carriers_with_passengers:
                if not carrier.position:
                    messages.append(f"Carrier {carrier.id} has no position, skipping unboard.")
                    continue
                carrier_hex = Hex.offset_to_axial(*carrier.position)
                if carrier.is_wing():
                    for p in carrier.passengers[:]:
                        if not self.game_state.map.can_unit_land_on_hex(p, carrier_hex):
                            messages.append(f"Cannot unboard {p.id} from {carrier.id}: destination terrain invalid")
                            continue
                        ok = self.unboard_unit(p)
                        if not ok:
                            messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or neutral country).")
                    continue
                if carrier.is_citadel():
                    for p in carrier.passengers[:]:
                        if not self.game_state.map.can_unit_land_on_hex(p, carrier_hex):
                            messages.append(f"Cannot unboard {p.id} from {carrier.id}: destination terrain invalid")
                            continue
                        ok = self.unboard_unit(p)
                        if not ok:
                            messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or neutral country).")
                    continue
                #is_coastal = self.game_state.map.is_coastal(carrier_hex)
                loc = self.game_state.map.get_location(carrier_hex)
                is_port = False
                if loc:
                    is_port = (loc.loc_type == LocType.PORT.value)

                if self.game_state.map.is_open_sea(carrier_hex):
                    messages.append(f"Carrier {carrier.id} is in open sea, cannot unboard.")
                    continue

                # Unboard all passengers (copy list since unboard_unit mutates passengers)
                for p in carrier.passengers[:]:
                    ok = self.unboard_unit(p)
                    if not ok:
                        messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")

                # Movement restriction: if carrier is in a coastal land hex (coastal but NOT port), it cannot move further this Turn
                if not is_port:
                    # Ensure movement_points exists
                    carrier.movement_points = 0

            return BoardActionResult(handled=True, messages=messages, force_sync=True)

        # Otherwise attempt boarding
        if not carriers:
            messages.append("No carrier selected to board units into.")
            return BoardActionResult(handled=True, messages=messages, force_sync=False)

        # Algorithm: load each ground army into the first selected carrier that can accept it.
        for army in armies:
            loaded = False
            for carrier in carriers:
                if self.board_unit(carrier, army):
                    messages.append(f"Boarded army {army.id} onto {carrier.id}")
                    loaded = True
                    break
            if not loaded:
                messages.append(f"Failed to board army {army.id} onto selected carriers.")

        # Load leaders into the first selected carrier that can accept each leader.
        if leaders and carriers:
            for l in leaders:
                loaded = False
                for carrier in carriers:
                    if self.board_unit(carrier, l):
                        messages.append(f"Boarded leader {l.id} onto {carrier.id}")
                        loaded = True
                        break
                if not loaded:
                    messages.append(f"Failed to board leader {l.id} onto selected carriers.")

        return BoardActionResult(handled=True, messages=messages, force_sync=True)
