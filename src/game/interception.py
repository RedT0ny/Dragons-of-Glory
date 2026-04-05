from src.content.constants import HL, NEUTRAL, WS
from src.content.specs import GamePhase, UnitRace, UnitType
from src.game.combat_reporting import show_combat_result_popup
from src.game.map import Hex


class InterceptionService:
    """Encapsulates interception detection, eligibility, and combat resolution."""

    def __init__(self, game_state, movement_service, rng):
        self.game_state = game_state
        self.movement_service = movement_service
        self.rng = rng
        self._interception_step_context = None
        self._interception_attempted_units = set()

    def should_check_interception(self, units):
        if not units:
            return False
        if getattr(self.game_state, "phase", None) != GamePhase.MOVEMENT:
            return False
        self.ensure_step_context()
        return all(getattr(u, "unit_type", None) in (UnitType.WING, UnitType.FLEET) for u in units)

    def ensure_step_context(self):
        context = (
            getattr(self.game_state, "turn", None),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._interception_step_context != context:
            self._interception_step_context = context
            self._interception_attempted_units = set()

    def maybe_apply_interception(self, moving_units, current_hex):
        """Checks if an interception attempt should occur against the moving units at their current hex."""
        in_range_groups = self.find_interceptor_groups_in_range(moving_units, current_hex)
        if not in_range_groups:
            return False

        # 20% possibility that the moving stack is spotted.
        if self.rng.random() >= 0.2:
            return False

        origin_offset, interceptors = self.rng.choice(in_range_groups)
        for unit in interceptors:
            self._interception_attempted_units.add((unit.id, getattr(unit, "ordinal", 1)))

        dist = self._hex_distance_from_offset(origin_offset, current_hex)
        if dist <= 0:
            return False
        roll = self.rng.randint(1, 6)
        print(f"Interception attempt by stack at {origin_offset}: roll {roll} vs distance {dist}.")
        if roll < dist:
            return False

        self.resolve_interception_attack(interceptors, moving_units, current_hex, origin_offset)
        return True

    def find_interceptor_groups_in_range(self, moving_units, current_hex):
        """Returns interceptor stacks in range, grouped by origin hex offset."""
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
            if not self.can_unit_intercept_target(unit, moving_units):
                continue
            if not self.dragon_interceptor_has_required_commander(unit):
                continue
            dist = self._hex_distance(unit, current_hex)
            if 1 <= dist <= 6:
                key = tuple(unit.position)
                by_hex.setdefault(key, []).append(unit)
        return list(by_hex.items())

    def resolve_interception_attack(self, interceptors, moving_units, moving_hex, origin_offset):
        """
        Resolves interception combat. Only air units (Wings/Fleets) participate as defenders.
        Ground units at the hex do not participate in interception combat.
        """
        origin_hex = Hex.offset_to_axial(*origin_offset)
        original_states = {}
        for interceptor in interceptors:
            original_states[interceptor] = {
                "movement_points": getattr(interceptor, "movement_points", None),
                "moved_this_turn": getattr(interceptor, "moved_this_turn", False),
                "attacked_this_turn": getattr(interceptor, "attacked_this_turn", False),
                "river_hexside": getattr(interceptor, "river_hexside", None),
            }

        adjacent_hex = self.find_interceptor_attack_hex_for_stack(interceptors, moving_hex, origin_hex)
        if adjacent_hex is None:
            print(f"Interception cancelled: no adjacent attack hex for stack at {origin_offset}.")
            return

        for interceptor in interceptors:
            if getattr(interceptor, "is_on_map", False):
                self.movement_service._teleport_unit_no_cost(interceptor, adjacent_hex)

        previous_active_player = self.game_state.active_player
        self.game_state.active_player = interceptors[0].allegiance
        try:
            live_interceptors = [u for u in interceptors if getattr(u, "is_on_map", False)]
            if live_interceptors:
                air_defenders = [
                    u for u in moving_units
                    if getattr(u, "is_on_map", False)
                    and getattr(u, "unit_type", None) in (UnitType.WING, UnitType.FLEET)
                ]
                resolution = self.game_state.combat_service.resolve_combat(live_interceptors, moving_hex)
                defenders_after = [
                    u for u in air_defenders
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
            self.movement_service._teleport_unit_no_cost(interceptor, origin_hex)
            state = original_states.get(interceptor, {})
            if state.get("movement_points") is not None:
                interceptor.movement_points = state["movement_points"]
            interceptor.moved_this_turn = state.get("moved_this_turn", False)
            interceptor.attacked_this_turn = state.get("attacked_this_turn", False)
            if hasattr(interceptor, "river_hexside"):
                interceptor.river_hexside = state.get("river_hexside", None)

    def find_interceptor_attack_hex_for_stack(self, interceptors, moving_hex, origin_hex):
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

    def can_unit_intercept_target(self, interceptor, moving_units):
        """
        Determines if the interceptor unit can attempt to intercept the moving units based on their types.
            - Fleets can only intercept if the moving stack includes at least one Fleet.
            - Wings can intercept if the moving stack includes at least one Wing or Fleet.
            - Other unit types cannot intercept.
            - Interceptors must be on the map to be eligible.
            - Interceptors must not have already attempted interception this turn.
            - Interceptors must meet special commander requirements (e.g. Dragon Wings).
        """
        moving_types = {getattr(u, "unit_type", None) for u in moving_units if getattr(u, "is_on_map", False)}
        if interceptor.unit_type == UnitType.FLEET:
            return UnitType.FLEET in moving_types
        if interceptor.is_wing():
            return bool(moving_types & {UnitType.WING, UnitType.FLEET})
        return False

    def dragon_interceptor_has_required_commander(self, interceptor):
        """
        Checks if a Dragon Wing interceptor has the required commander to intercept.
        - HL Dragon Wings can only intercept if they have a Dragon Emperor or Dragon Highlord of its flight on board.
        - WS Dragon Wings can only intercept if they have an Elf/Solamnic commander on board.
        - Other units do not have commander requirements.
        """
        if not interceptor.is_wing():
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
        if interceptor.allegiance == WS:
            for p in passengers:
                if not (hasattr(p, "is_leader") and p.is_leader()):
                    continue
                p_race = getattr(p, "race", None)
                if p_race in (UnitRace.ELF, UnitRace.SOLAMNIC):
                    return True
            return False
        return True

    @staticmethod
    def _hex_distance(unit, target_hex):
        start = Hex.offset_to_axial(*unit.position)
        return start.distance_to(target_hex)

    @staticmethod
    def _hex_distance_from_offset(offset, target_hex):
        start = Hex.offset_to_axial(*offset)
        return start.distance_to(target_hex)
