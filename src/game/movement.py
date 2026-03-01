from dataclasses import dataclass
import heapq
import random
from typing import List, Tuple

from src.content.constants import HL, NEUTRAL
from src.content.specs import GamePhase, HexsideType, LocType, UnitRace, UnitType
from src.game.map import Hex
from src.game.combat_reporting import show_combat_result_popup


def effective_movement_points(unit):
    current = getattr(unit, "movement_points", unit.movement)
    # Passengers can reduce effective movement (e.g. Wings/Fleets).
    return min(current, unit.movement)


def evaluate_unit_move(game_state, unit, target_hex):
    """
    Shared movement validation/cost calculation used by UI and move execution.
    Returns: (ok, reason, cost, start_hex, fleet_state_path)
    """
    if getattr(unit, "transport_host", None) is not None:
        return False, f"{unit.id} is transported and cannot move independently.", 0, None, []

    if getattr(unit, "carried_by_citadel_this_turn", False):
        return False, f"{unit.id} was carried by a citadel and cannot move independently this turn.", 0, None, []

    if unit.unit_type != UnitType.FLEET and not game_state.map.can_unit_land_on_hex(unit, target_hex):
        return False, f"{unit.id} cannot end movement on that terrain.", 0, None, []

    if not unit.position or unit.position[0] is None or unit.position[1] is None:
        return True, None, 0, None, []

    max_mp = effective_movement_points(unit)
    start_hex = Hex.offset_to_axial(*unit.position)
    if unit.unit_type == UnitType.FLEET:
        state_path, cost = game_state.map.find_fleet_route(unit, start_hex, target_hex)
        if cost == float("inf") or (not state_path and start_hex != target_hex):
            return False, f"{unit.id} has no valid path.", 0, start_hex, []
        if cost > max_mp:
            return False, f"{unit.id} lacks movement points.", cost, start_hex, state_path
        return True, None, cost, start_hex, state_path

    path = game_state.map.find_shortest_path(unit, start_hex, target_hex)
    if not path and start_hex != target_hex:
        return False, f"{unit.id} has no valid path.", 0, start_hex, []

    cost = 0
    current = start_hex
    for next_step in path:
        step_cost = game_state.map.get_movement_cost(unit, current, next_step)
        cost += step_cost
        current = next_step

    if cost > max_mp:
        return False, f"{unit.id} lacks movement points.", cost, start_hex, []

    return True, None, cost, start_hex, []


@dataclass
class BoardActionResult:
    handled: bool
    messages: List[str]
    force_sync: bool


@dataclass
class MovementRangeResult:
    reachable_coords: List[Tuple[int, int]]
    neutral_warning_coords: List[Tuple[int, int]]

@dataclass
class MoveUnitsResult:
    moved: List[object]
    errors: List[str]


@dataclass
class NeutralEntryDecision:
    is_neutral_entry: bool
    country_id: str | None = None
    blocked_message: str | None = None
    confirmation_prompt: str | None = None


class MovementService:
    def __init__(self, game_state):
        self.game_state = game_state
        self._interception_step_context = None
        self._interception_attempted_units = set()

    def get_reachable_hexes(self, units):
        """
        Returns reachable hexes plus neutral-border warnings for UI highlighting.
        """
        if not units:
            return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])
        if all(u.unit_type == UnitType.FLEET for u in units):
            start_hex, _ = self._get_stack_start_and_min_mp(units)
            # A selected "stack" of fleets must be co-located.
            if not start_hex:
                return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])
            most_restrictive_fleet = min(units, key=effective_movement_points)
            return self._range_result_from_hexes(
                self.game_state.map.get_reachable_hexes_for_fleet(most_restrictive_fleet)
            )

        start_hex, min_mp = self._get_stack_start_and_min_mp(units)
        if not start_hex or min_mp <= 0:
            return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])

        if self._is_neutral_hex(start_hex):
            return self._range_result_from_hexes(self.game_state.map.get_reachable_hexes(units))

        return self._get_neutral_limited_range(units, start_hex, min_mp)

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
        if len(units) > 1 and any(self._is_ground_army(u) for u in units):
            ok, reason = self._can_stack_reach_target(units, target_hex)
            if not ok:
                return MoveUnitsResult(moved=[], errors=[reason or "Selected stack cannot move there."])

            target_offset = target_hex.axial_to_offset()
            moved = []
            ordered_units = sorted(units, key=lambda u: 0 if self._is_ground_army(u) else 1)
            for unit in ordered_units:
                self.game_state.move_unit(unit, target_hex)
                if getattr(unit, "position", None) != target_offset:
                    return MoveUnitsResult(
                        moved=moved,
                        errors=[f"{unit.id} cannot move."],
                    )
                moved.append(unit)
            return MoveUnitsResult(moved=moved, errors=[])

        if self._should_check_interception(units):
            return self._move_units_with_interception(units, target_hex)

        errors = []
        for unit in units:
            ok, reason = self._can_unit_reach_target(unit, target_hex)
            if not ok:
                errors.append(reason or f"{unit.id} cannot move.")

        if errors:
            return MoveUnitsResult(moved=[], errors=errors)

        moved = []
        for unit in units:
            self.game_state.move_unit(unit, target_hex)
            moved.append(unit)
        return MoveUnitsResult(moved=moved, errors=[])

    def _should_check_interception(self, units):
        if not units:
            return False
        if getattr(self.game_state, "phase", None) != GamePhase.MOVEMENT:
            return False
        self._ensure_interception_step_context()
        return all(getattr(u, "unit_type", None) in (UnitType.WING, UnitType.FLEET) for u in units)

    def _ensure_interception_step_context(self):
        context = (
            getattr(self.game_state, "turn", None),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._interception_step_context != context:
            self._interception_step_context = context
            self._interception_attempted_units = set()

    def _move_units_with_interception(self, units, target_hex):
        plans = {}
        for unit in units:
            ok, reason, cost, _, state_path = evaluate_unit_move(self.game_state, unit, target_hex)
            if not ok:
                return MoveUnitsResult(moved=[], errors=[reason or f"{unit.id} cannot move."])
            final_hexside = getattr(unit, "river_hexside", None)
            if unit.unit_type == UnitType.FLEET and state_path:
                final_hexside = state_path[-1][1]
            plans[unit] = {
                "cost": cost,
                "final_hexside": final_hexside,
                "state_path": state_path,
            }

        lead = units[0]
        path = self._build_movement_hex_path(
            units,
            target_hex,
            precomputed_state_path=plans.get(lead, {}).get("state_path"),
        )
        if path is None:
            return MoveUnitsResult(moved=[], errors=["Selected stack has no valid path."])
        if not path:
            return MoveUnitsResult(moved=list(units), errors=[])

        for step_hex in path:
            for unit in list(units):
                if not getattr(unit, "is_on_map", False):
                    continue
                self._relocate_unit_for_interception_step(unit, step_hex)

            movers_alive = [u for u in units if getattr(u, "is_on_map", False)]
            if not movers_alive:
                return MoveUnitsResult(moved=[], errors=[])

            intercepted = self._maybe_apply_interception(movers_alive, step_hex)
            movers_alive = [u for u in units if getattr(u, "is_on_map", False)]
            if not movers_alive:
                return MoveUnitsResult(moved=[], errors=[])

            if intercepted:
                print(f"Interception resolved at {step_hex.axial_to_offset()}.")

        for unit in units:
            if not getattr(unit, "is_on_map", False):
                continue
            plan = plans.get(unit)
            if not plan:
                continue
            self._finalize_interception_move(unit, plan)

        return MoveUnitsResult(moved=[u for u in units if getattr(u, "is_on_map", False)], errors=[])

    def _build_movement_hex_path(self, units, target_hex, precomputed_state_path=None):
        lead = units[0]
        if not getattr(lead, "position", None) or lead.position[0] is None or lead.position[1] is None:
            return []
        start_hex = Hex.offset_to_axial(*lead.position)
        if start_hex == target_hex:
            return []

        if lead.unit_type == UnitType.FLEET:
            state_path = precomputed_state_path
            if state_path is None:
                ok, reason, _, _, state_path = evaluate_unit_move(self.game_state, lead, target_hex)
                if not ok:
                    return None
            if not state_path:
                return []
            hex_path = []
            prev_hex = state_path[0][0]
            for curr_hex, _ in state_path[1:]:
                if curr_hex != prev_hex:
                    hex_path.append(curr_hex)
                prev_hex = curr_hex
            return hex_path

        path = self.game_state.map.find_shortest_path(lead, start_hex, target_hex)
        if not path and start_hex != target_hex:
            return None
        return path

    def _maybe_apply_interception(self, moving_units, current_hex):
        in_range_groups = self._find_interceptor_groups_in_range(moving_units, current_hex)
        if not in_range_groups:
            return False

        # Interception attempts are stochastic and can happen on any in-range movement hex.
        if random.random() >= 0.5:
            return False

        origin_offset, interceptors = random.choice(in_range_groups)
        for unit in interceptors:
            self._interception_attempted_units.add((unit.id, getattr(unit, "ordinal", 1)))

        dist = self._hex_distance_from_offset(origin_offset, current_hex)
        if dist <= 0:
            return False
        roll = random.randint(1, 6)
        print(
            f"Interception attempt by stack at {origin_offset}: roll {roll} vs distance {dist}."
        )
        if roll < dist:
            return False

        self._resolve_interception_attack(interceptors, moving_units, current_hex, origin_offset)
        return True

    def _find_interceptor_groups_in_range(self, moving_units, current_hex):
        mover_side = moving_units[0].allegiance
        by_hex = {}
        for unit in self.game_state.units:
            if unit.allegiance in (mover_side, NEUTRAL, None):
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            if unit.unit_type not in (UnitType.WING, UnitType.FLEET):
                continue
            if not unit.position or unit.position[0] is None or unit.position[1] is None:
                continue
            if (unit.id, getattr(unit, "ordinal", 1)) in self._interception_attempted_units:
                continue
            if not self._can_unit_intercept_target(unit, moving_units):
                continue
            if not self._dragon_interceptor_has_required_commander(unit):
                continue
            dist = self._hex_distance(unit, current_hex)
            if 1 <= dist <= 6:
                key = tuple(unit.position)
                by_hex.setdefault(key, []).append(unit)
        return list(by_hex.items())

    def _relocate_unit_for_interception_step(self, unit, target_hex):
        self.game_state.map.remove_unit_from_spatial_map(unit)
        unit.position = target_hex.axial_to_offset()
        unit.escaped = False
        self.game_state.map.add_unit_to_spatial_map(unit)

        passengers = getattr(unit, "passengers", None)
        if passengers:
            for p in passengers:
                p.position = unit.position
                p.is_transported = True
                p.transport_host = unit

        apply_escape = getattr(self.game_state, "_apply_escape_if_eligible", None)
        if callable(apply_escape):
            apply_escape(unit, unit.position)

    def _finalize_interception_move(self, unit, plan):
        if not hasattr(unit, "movement_points"):
            unit.movement_points = unit.movement
        cost = int(plan.get("cost", 0) or 0)
        effective_mp = effective_movement_points(unit)
        if cost > 0:
            unit.movement_points = max(0, effective_mp - cost)
        if getattr(self.game_state, "phase", None) == GamePhase.MOVEMENT:
            unit.moved_this_turn = True
            if unit.unit_type == UnitType.FLEET:
                unit.river_hexside = plan.get("final_hexside", getattr(unit, "river_hexside", None))

    @staticmethod
    def _hex_distance(unit, target_hex):
        start = Hex.offset_to_axial(*unit.position)
        return start.distance_to(target_hex)

    @staticmethod
    def _hex_distance_from_offset(offset, target_hex):
        start = Hex.offset_to_axial(*offset)
        return start.distance_to(target_hex)

    def _resolve_interception_attack(self, interceptors, moving_units, moving_hex, origin_offset):
        origin_hex = Hex.offset_to_axial(*origin_offset)
        original_states = {}
        for interceptor in interceptors:
            original_states[interceptor] = {
                "movement_points": getattr(interceptor, "movement_points", None),
                "moved_this_turn": getattr(interceptor, "moved_this_turn", False),
                "attacked_this_turn": getattr(interceptor, "attacked_this_turn", False),
                "river_hexside": getattr(interceptor, "river_hexside", None),
            }

        adjacent_hex = self._find_interceptor_attack_hex_for_stack(interceptors, moving_hex, origin_hex)
        if adjacent_hex is None:
            print(f"Interception cancelled: no adjacent attack hex for stack at {origin_offset}.")
            return

        for interceptor in interceptors:
            if getattr(interceptor, "is_on_map", False):
                self._teleport_unit_no_cost(interceptor, adjacent_hex)

        previous_active_player = self.game_state.active_player
        self.game_state.active_player = interceptors[0].allegiance
        try:
            live_interceptors = [u for u in interceptors if getattr(u, "is_on_map", False)]
            if live_interceptors:
                resolution = self.game_state.resolve_combat(live_interceptors, moving_hex)
                defenders_after = [
                    u for u in self.game_state.get_units_at(moving_hex)
                    if getattr(u, "is_on_map", False)
                    and getattr(u, "allegiance", None) != getattr(live_interceptors[0], "allegiance", None)
                ]
                show_combat_result_popup(
                    self.game_state,
                    title="Interception Details",
                    attackers=live_interceptors,
                    defenders=defenders_after,
                    resolution=resolution,
                    context="interception",
                    target_hex=moving_hex,
                )
        finally:
            self.game_state.active_player = previous_active_player

        for interceptor in interceptors:
            if not getattr(interceptor, "is_on_map", False):
                continue
            self._teleport_unit_no_cost(interceptor, origin_hex)
            state = original_states.get(interceptor, {})
            if state.get("movement_points") is not None:
                interceptor.movement_points = state["movement_points"]
            interceptor.moved_this_turn = state.get("moved_this_turn", False)
            interceptor.attacked_this_turn = state.get("attacked_this_turn", False)
            if hasattr(interceptor, "river_hexside"):
                interceptor.river_hexside = state.get("river_hexside", None)

    def _find_interceptor_attack_hex_for_stack(self, interceptors, moving_hex, origin_hex):
        candidates = []
        if not interceptors:
            return None
        for neighbor in moving_hex.neighbors():
            col, row = neighbor.axial_to_offset()
            if not self.game_state.is_hex_in_bounds(col, row):
                continue
            if not self.game_state.map.can_stack_move_to(interceptors, neighbor):
                continue

            feasible = True
            max_cost = 0
            for interceptor in interceptors:
                if not self.game_state.map.can_unit_land_on_hex(interceptor, neighbor):
                    feasible = False
                    break
                if interceptor.unit_type == UnitType.FLEET:
                    state_path, cost = self.game_state.map.find_fleet_route(interceptor, origin_hex, neighbor)
                    if cost == float("inf") or (not state_path and origin_hex != neighbor):
                        feasible = False
                        break
                else:
                    path = self.game_state.map.find_shortest_path(interceptor, origin_hex, neighbor)
                    if not path and origin_hex != neighbor:
                        feasible = False
                        break
                    cost = len(path)
                max_cost = max(max_cost, cost)
            if not feasible:
                continue
            candidates.append((max_cost, neighbor))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _can_unit_intercept_target(self, interceptor, moving_units):
        moving_types = {getattr(u, "unit_type", None) for u in moving_units if getattr(u, "is_on_map", False)}
        if interceptor.unit_type == UnitType.FLEET:
            return UnitType.FLEET in moving_types
        if interceptor.unit_type == UnitType.WING:
            return bool(moving_types & {UnitType.WING, UnitType.FLEET})
        return False

    def _dragon_interceptor_has_required_commander(self, interceptor):
        if getattr(interceptor, "unit_type", None) != UnitType.WING:
            return True
        if getattr(interceptor, "race", None) != UnitRace.DRAGON:
            return True

        passengers = list(getattr(interceptor, "passengers", []) or [])
        if interceptor.allegiance == HL:
            dragonflight = getattr(getattr(interceptor, "spec", None), "dragonflight", None)
            for p in passengers:
                if not (hasattr(p, "is_leader") and p.is_leader()):
                    continue
                if getattr(p, "unit_type", None) == UnitType.EMPEROR:
                    return True
                if getattr(p, "unit_type", None) == UnitType.HIGHLORD:
                    p_flight = getattr(getattr(p, "spec", None), "dragonflight", None)
                    if dragonflight and p_flight == dragonflight:
                        return True
            return False
        if interceptor.allegiance != HL:
            for p in passengers:
                if not (hasattr(p, "is_leader") and p.is_leader()):
                    continue
                p_race = getattr(p, "race", None)
                if p_race in (UnitRace.ELF, UnitRace.SOLAMNIC):
                    return True
            return False
        return True

    def _teleport_unit_no_cost(self, unit, target_hex):
        self.game_state.map.remove_unit_from_spatial_map(unit)
        unit.position = target_hex.axial_to_offset()
        self.game_state.map.add_unit_to_spatial_map(unit)
        passengers = getattr(unit, "passengers", None)
        if passengers:
            for p in passengers:
                p.position = unit.position
                p.is_transported = True
                p.transport_host = unit

    @staticmethod
    def _is_ground_army(unit):
        return (
            hasattr(unit, "is_army")
            and unit.is_army()
            and unit.unit_type not in (UnitType.FLEET, UnitType.WING)
        )

    def _can_stack_reach_target(self, units, target_hex):
        start_hex, _ = self._get_stack_start_and_min_mp(units)
        if not start_hex:
            return False, "Selected units are not in the same hex."
        if start_hex == target_hex:
            return True, None
        reachable = self.game_state.map.get_reachable_hexes(units)
        if target_hex in reachable:
            return True, None
        return False, "Selected stack has no valid path."

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

    def _get_stack_start_and_min_mp(self, units):
        start_hex = None
        min_mp = 999

        for unit in units:
            if not getattr(unit, 'is_on_map', True):
                continue
            if hasattr(unit, 'position') and unit.position:
                col, row = unit.position
                h = Hex.offset_to_axial(col, row)
                if start_hex is None:
                    start_hex = h
                elif start_hex != h:
                    return None, 0

            m = self._unit_movement_points(unit)
            min_mp = min(min_mp, m)

        return start_hex, min_mp

    def _is_neutral_hex(self, hex_obj):
        col, row = hex_obj.axial_to_offset()
        country = self.game_state.get_country_by_hex(col, row)
        return bool(country and country.allegiance == NEUTRAL)

    def _get_neutral_limited_range(self, units, start_hex, min_mp):
        board = self.game_state.map
        frontier = []
        heapq.heappush(frontier, (0, start_hex, False))
        cost_so_far = {(start_hex, False): 0}

        reachable_hexes = []
        warning_hexes = []
        neutral_cache = {}

        def is_neutral_cached(hex_obj):
            key = (hex_obj.q, hex_obj.r)
            if key not in neutral_cache:
                neutral_cache[key] = self._is_neutral_hex(hex_obj)
            return neutral_cache[key]

        while frontier:
            current_cost, current_hex, entered_neutral = heapq.heappop(frontier)

            if current_cost > min_mp:
                continue

            if current_cost > cost_so_far.get((current_hex, entered_neutral), float('inf')):
                continue

            if current_hex != start_hex:
                if board.can_stack_move_to(units, current_hex) and all(
                    board.can_unit_land_on_hex(u, current_hex) for u in units
                ):
                    if is_neutral_cached(current_hex):
                        warning_hexes.append(current_hex)
                    else:
                        reachable_hexes.append(current_hex)

            if entered_neutral:
                continue

            for next_hex in current_hex.neighbors():
                # 1. Bounds check
                c, r = next_hex.axial_to_offset()
                if not (0 <= c < board.width and 0 <= r < board.height):
                    continue

                stack_cost = self._stack_step_cost(units, current_hex, next_hex, board)
                if stack_cost is None:
                    continue

                new_cost = current_cost + stack_cost
                if new_cost <= min_mp:
                    next_entered_neutral = is_neutral_cached(next_hex)
                    key = (next_hex, next_entered_neutral)
                    if next_hex == start_hex:
                        continue
                    if key not in cost_so_far or new_cost < cost_so_far[key]:
                        cost_so_far[key] = new_cost
                        heapq.heappush(frontier, (new_cost, next_hex, next_entered_neutral))

        return MovementRangeResult(
            reachable_coords=[h.axial_to_offset() for h in reachable_hexes],
            neutral_warning_coords=[h.axial_to_offset() for h in warning_hexes]
        )

    def _stack_step_cost(self, units, current_hex, next_hex, board):
        # Check 1: Enemy occupancy based on stack composition.
        if not board.can_stack_enter_enemy_occupied_hex(units, next_hex):
            return None

        stack_cost = 0
        for unit in units:
            # Check 2: Sea Barrier
            if unit.unit_type not in (UnitType.WING, UnitType.CITADEL):
                hexside = board.get_effective_hexside(current_hex, next_hex)
                if hexside in (HexsideType.SEA, HexsideType.SEA.value):
                    return None

            # Check 3: ZOC (Rule 5) applies only to non-cavalry Army units.
            zoc_restricted = bool(unit.is_army() and unit.unit_type != UnitType.CAVALRY)
            if zoc_restricted and board.is_adjacent_to_enemy(current_hex, unit) and board.is_adjacent_to_enemy(next_hex, unit):
                return None

            # Check 4: Movement Cost
            cost = board.get_movement_cost(unit, current_hex, next_hex)
            if cost == float('inf') or cost is None:
                return None

            stack_cost = max(stack_cost, cost)
        return stack_cost

    def get_invasion_force(self, country_id):
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

        stacks_by_hex = self._get_hl_stacks_with_passengers()
        if not stacks_by_hex:
            return {
                "strength": 0,
                "units": [],
                "border_hexes": set(),
                "connected_hexes": set(),
                "reason": "No Highlord stacks available."
            }

        border_hexes = set()
        for hex_obj, stack_units in stacks_by_hex.items():
            if self._hex_adjacent_to_country(hex_obj, target_hexes):
                if self._stack_can_enter_country(hex_obj, stack_units, target_hexes):
                    border_hexes.add(hex_obj)

        if not border_hexes:
            return {
                "strength": 0,
                "units": [],
                "border_hexes": set(),
                "connected_hexes": set(),
                "reason": "No eligible Highlord stacks adjacent to the border."
            }

        connected_hexes = self._collect_connected_stack_hexes(border_hexes, stacks_by_hex.keys())
        eligible_units = self._collect_invasion_units(connected_hexes, stacks_by_hex, target_hexes)
        strength = sum(u.combat_rating for u in eligible_units)

        return {
            "strength": strength,
            "units": eligible_units,
            "border_hexes": border_hexes,
            "connected_hexes": connected_hexes,
            "reason": None
        }

    def _get_hl_stacks_with_passengers(self):
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

    def _hex_adjacent_to_country(self, hex_obj, target_hexes):
        return any(neighbor.axial_to_offset() in target_hexes for neighbor in hex_obj.neighbors())

    def _stack_can_enter_country(self, hex_obj, stack_units, target_hexes):
        combat_units = [u for u in stack_units if u.unit_type != UnitType.FLEET]
        if not combat_units:
            return False

        for neighbor in hex_obj.neighbors():
            if neighbor.axial_to_offset() not in target_hexes:
                continue
            if not self.game_state.map.can_stack_move_to(combat_units, neighbor):
                continue
            for unit in combat_units:
                if self._unit_can_enter_hex(unit, hex_obj, neighbor):
                    return True

        return False

    def _collect_connected_stack_hexes(self, border_hexes, all_stack_hexes):
        remaining = set(all_stack_hexes)
        connected = set()
        frontier = list(border_hexes)

        for hex_obj in border_hexes:
            if hex_obj in remaining:
                remaining.remove(hex_obj)
            connected.add(hex_obj)

        while frontier:
            current = frontier.pop()
            for neighbor in current.neighbors():
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    connected.add(neighbor)
                    frontier.append(neighbor)

        return connected

    def _collect_invasion_units(self, connected_hexes, stacks_by_hex, target_hexes):
        eligible = []
        for hex_obj in connected_hexes:
            stack_units = stacks_by_hex.get(hex_obj, [])
            for unit in stack_units:
                if unit.unit_type == UnitType.FLEET:
                    continue
                if not self._unit_has_movement(unit):
                    continue
                if self._unit_can_reach_country(unit, hex_obj, target_hexes):
                    eligible.append(unit)
        return eligible

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

        cost = self.game_state.map.get_movement_cost(unit, from_hex, target_hex)
        if cost == float('inf') or cost is None:
            return False
        return self._unit_movement_points(unit) >= cost

    def _unit_has_movement(self, unit):
        return self._unit_movement_points(unit) > 0

    def _unit_movement_points(self, unit):
        return effective_movement_points(unit)

    def _can_unit_reach_target(self, unit, target_hex):
        ok, reason, _, _, _ = evaluate_unit_move(self.game_state, unit, target_hex)
        return ok, reason

    def handle_board_action(self, selected_units):
        if not selected_units:
            return BoardActionResult(handled=False, messages=[], force_sync=False)

        messages = []

        # Separate carriers, armies, leaders
        carriers = [u for u in selected_units if u.unit_type == UnitType.FLEET or getattr(u, 'passengers', None) is not None]
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
                if carrier.unit_type == UnitType.WING:
                    if not self.game_state.map.can_unit_land_on_hex(u, carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: destination terrain invalid for passenger")
                        continue
                elif carrier.unit_type == UnitType.CITADEL:
                    if not self.game_state.map.can_unit_land_on_hex(u, carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: destination terrain invalid for passenger")
                        continue
                else:
                    # Check carrier hex is coastal
                    if not self.game_state.map.is_coastal(carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: carrier not in coastal hex")
                        continue
                success = self.game_state.unboard_unit(u)
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
                if carrier.unit_type == UnitType.WING:
                    for p in carrier.passengers[:]:
                        if not self.game_state.map.can_unit_land_on_hex(p, carrier_hex):
                            messages.append(f"Cannot unboard {p.id} from {carrier.id}: destination terrain invalid")
                            continue
                        ok = self.game_state.unboard_unit(p)
                        if not ok:
                            messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")
                    continue
                if carrier.unit_type == UnitType.CITADEL:
                    for p in carrier.passengers[:]:
                        if not self.game_state.map.can_unit_land_on_hex(p, carrier_hex):
                            messages.append(f"Cannot unboard {p.id} from {carrier.id}: destination terrain invalid")
                            continue
                        ok = self.game_state.unboard_unit(p)
                        if not ok:
                            messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")
                    continue
                is_coastal = self.game_state.map.is_coastal(carrier_hex)
                loc = self.game_state.map.get_location(carrier_hex)
                is_port = False
                if loc:
                    is_port = (loc.loc_type == LocType.PORT.value)

                if not (is_coastal or is_port):
                    messages.append(f"Carrier {carrier.id} not in coastal hex or port, cannot unboard.")
                    continue

                # Unboard all passengers (copy list since unboard_unit mutates passengers)
                for p in carrier.passengers[:]:
                    ok = self.game_state.unboard_unit(p)
                    if not ok:
                        messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")

                # Movement restriction: if carrier is in a coastal land hex (coastal but NOT port), it cannot move further this Turn
                if is_coastal and not is_port:
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
                if self.game_state.board_unit(carrier, army):
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
                    if self.game_state.board_unit(carrier, l):
                        messages.append(f"Boarded leader {l.id} onto {carrier.id}")
                        loaded = True
                        break
                if not loaded:
                    messages.append(f"Failed to board leader {l.id} onto selected carriers.")

        return BoardActionResult(handled=True, messages=messages, force_sync=True)
