
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import UnitType, UnitState, LocType, UnitRace
from src.game.map import Hex
from src.game.combat_reporting import show_combat_result_popup


def _enemy_of(side: str) -> Optional[str]:
    if side == HL:
        return WS
    if side == WS:
        return HL
    return None


def _unit_key(unit) -> Tuple[str, int]:
    return (str(getattr(unit, "id", "")), int(getattr(unit, "ordinal", 1) or 1))


def _hex_distance(a: Hex, b: Hex) -> int:
    return a.distance_to(b)


def _overlay_value(overlay, col: int, row: int, default: float = 0.0) -> float:
    if overlay is None:
        return default
    return float(overlay.values.get((col, row), default) or default)


def _slugify(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


@dataclass
class Objective:
    id: str
    coords: Tuple[int, int]
    owner: str
    value: float
    is_capital: bool = False
    loc_type: Optional[str] = None
    country_id: Optional[str] = None


@dataclass
class StrategicPlan:
    posture: str
    objectives: List[Objective]
    transport_campaign: bool = False
    invasion_target: Optional[str] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class TaskGroup:
    units: List[object]
    hex: Hex
    power: float
    has_army: bool
    has_wing: bool
    has_fleet: bool
    mobile_units: List[object]


@dataclass
class Mission:
    group: TaskGroup
    mission_type: str
    target_hex: Optional[Hex]
    objective: Optional[Objective]
    priority: float


@dataclass
class TacticalAction:
    kind: str
    group: TaskGroup
    target_hex: Optional[Hex]
    score: float
    details: str = ""


@dataclass
class AIContext:
    game_state: Any
    movement_service: Any
    diplomacy_service: Any
    side: str
    enemy: str
    turn: int
    phase: Any
    control_facts: Any
    overlays: Dict[str, Any]
    objectives: List[Objective]
    friendly_units: List[object]
    enemy_units: List[object]


class StrategicPlanner:
    def build_plan(self, ctx: AIContext) -> StrategicPlan:
        posture, notes = self._choose_posture(ctx)
        objectives = self._prioritize_objectives(ctx)
        transport_campaign = self._should_use_transport(ctx, objectives)
        invasion_target = self._choose_invasion_target(ctx, objectives)
        return StrategicPlan(
            posture=posture,
            objectives=objectives,
            transport_campaign=transport_campaign,
            invasion_target=invasion_target,
            notes=notes,
        )

    def _choose_posture(self, ctx: AIContext) -> Tuple[str, List[str]]:
        notes = []
        friendly_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in ctx.friendly_units
            if ctx.game_state.is_combat_unit(u)
        )
        enemy_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in ctx.enemy_units
            if ctx.game_state.is_combat_unit(u)
        )
        territory = ctx.overlays.get("territory")
        friendly_hexes = sum(1 for v in territory.values.values() if v == ctx.side) if territory else 0
        enemy_hexes = sum(1 for v in territory.values.values() if v == ctx.enemy) if territory else 0

        ratio = friendly_power / max(enemy_power, 1.0)
        posture = "balanced"
        if ratio < 0.85 or friendly_hexes < enemy_hexes * 0.8:
            posture = "defensive"
        elif ratio > 1.2 or friendly_hexes > enemy_hexes * 1.2:
            posture = "offensive"

        end_turn = int(getattr(ctx.game_state.scenario_spec, "end_turn", 0) or 0)
        if end_turn:
            turns_left = max(0, end_turn - ctx.turn)
            if turns_left <= 2:
                victory_eval = getattr(ctx.game_state, "victory_evaluator", None)
                if victory_eval:
                    status = victory_eval.evaluate()
                    points = status.minor_points
                    if points.get(ctx.side, 0) < points.get(ctx.enemy, 0):
                        posture = "offensive"
                        notes.append("late-game push")
        notes.append(f"power_ratio={ratio:.2f}")
        notes.append(f"territory={friendly_hexes}:{enemy_hexes}")
        return posture, notes

    def _prioritize_objectives(self, ctx: AIContext) -> List[Objective]:
        objectives = list(ctx.objectives)
        objectives.sort(key=lambda o: (o.value, o.owner != ctx.side, o.is_capital), reverse=True)
        return objectives

    def _should_use_transport(self, ctx: AIContext, objectives: List[Objective]) -> bool:
        fleets = [u for u in ctx.friendly_units if getattr(u, "unit_type", None) == UnitType.FLEET]
        if not fleets:
            return False
        if not objectives:
            return False
        for obj in objectives:
            if obj.owner != ctx.side:
                hex_obj = Hex.offset_to_axial(obj.coords[0], obj.coords[1])
                if ctx.game_state.map.is_coastal(hex_obj):
                    return True
        return False

    def _choose_invasion_target(self, ctx: AIContext, objectives: List[Objective]) -> Optional[str]:
        if ctx.side != HL:
            return None
        neutrals = [c for c in ctx.game_state.countries.values() if c.allegiance == NEUTRAL]
        if not neutrals:
            return None
        best = None
        best_score = float("-inf")
        obj_hexes = [Hex.offset_to_axial(o.coords[0], o.coords[1]) for o in objectives]
        for country in neutrals:
            score = 0.0
            alignment = getattr(country, "alignment", (0, 0))
            score += float(alignment[1] if len(alignment) > 1 else 0) * 10
            score += float(getattr(country, "strength", 0) or 0)
            if obj_hexes:
                distances = []
                for loc in country.locations.values():
                    if not loc.coords:
                        continue
                    loc_hex = Hex.offset_to_axial(*loc.coords)
                    distances.append(min(loc_hex.distance_to(h) for h in obj_hexes))
                if distances:
                    score += max(0.0, 20.0 - (sum(distances) / len(distances)))
            if score > best_score:
                best_score = score
                best = country.id
        return best

class OperationalPlanner:
    def build_task_groups(self, ctx: AIContext) -> List[TaskGroup]:
        board = ctx.game_state.map
        groups = []
        for (q, r), units in sorted(board.unit_map.items(), key=lambda item: (item[0][1], item[0][0])):
            stack = [u for u in units if getattr(u, "allegiance", None) == ctx.side and getattr(u, "is_on_map", False)]
            if not stack:
                continue
            hex_obj = Hex(q, r)
            combat_units = [u for u in stack if ctx.game_state.is_combat_unit(u)]
            power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in combat_units)
            has_army = any(getattr(u, "is_army", lambda: False)() for u in stack)
            has_wing = any(getattr(u, "is_wing", lambda: False)() for u in stack)
            has_fleet = any(getattr(u, "unit_type", None) == UnitType.FLEET for u in stack)
            mobile_units = [
                u for u in stack
                if getattr(u, "transport_host", None) is None
                and float(getattr(u, "movement_points", 0) or 0) > 0
            ]
            groups.append(TaskGroup(
                units=stack,
                hex=hex_obj,
                power=power,
                has_army=has_army,
                has_wing=has_wing,
                has_fleet=has_fleet,
                mobile_units=mobile_units,
            ))
        return groups

    def build_missions(self, ctx: AIContext, plan: StrategicPlan, groups: List[TaskGroup]) -> List[Mission]:
        missions = []
        threat = ctx.overlays.get("threat")
        locations = self._collect_location_map(ctx)

        for group in groups:
            col, row = group.hex.axial_to_offset()
            loc = locations.get((col, row))
            local_threat = _overlay_value(threat, col, row, 0.0)

            if loc and loc.occupier == ctx.side and local_threat >= 1.5:
                missions.append(Mission(
                    group=group,
                    mission_type="defend",
                    target_hex=group.hex,
                    objective=None,
                    priority=80 + local_threat * 10,
                ))
                continue

            objective, distance = self._nearest_objective(group.hex, plan.objectives)
            if plan.posture == "defensive":
                if loc and loc.occupier == ctx.side:
                    missions.append(Mission(
                        group=group,
                        mission_type="hold",
                        target_hex=group.hex,
                        objective=None,
                        priority=40 + local_threat,
                    ))
                elif objective:
                    missions.append(Mission(
                        group=group,
                        mission_type="reinforce",
                        target_hex=Hex.offset_to_axial(objective.coords[0], objective.coords[1]),
                        objective=objective,
                        priority=max(10.0, objective.value - distance * 2),
                    ))
                else:
                    missions.append(Mission(
                        group=group,
                        mission_type="screen",
                        target_hex=group.hex,
                        objective=None,
                        priority=20,
                    ))
            else:
                if objective:
                    mission_type = "push_objective" if objective.owner != ctx.side else "secure"
                    missions.append(Mission(
                        group=group,
                        mission_type=mission_type,
                        target_hex=Hex.offset_to_axial(objective.coords[0], objective.coords[1]),
                        objective=objective,
                        priority=max(15.0, objective.value - distance * 1.5),
                    ))
                else:
                    missions.append(Mission(
                        group=group,
                        mission_type="screen",
                        target_hex=group.hex,
                        objective=None,
                        priority=15,
                    ))

        missions.sort(key=lambda m: (m.priority, m.group.power), reverse=True)
        return missions

    @staticmethod
    def _collect_location_map(ctx: AIContext) -> Dict[Tuple[int, int], object]:
        locations = {}
        for country in ctx.game_state.countries.values():
            for loc in country.locations.values():
                if not loc.coords:
                    continue
                locations[(loc.coords[0], loc.coords[1])] = loc
        return locations

    @staticmethod
    def _nearest_objective(start_hex: Hex, objectives: List[Objective]) -> Tuple[Optional[Objective], float]:
        if not objectives:
            return None, 999.0
        best = None
        best_dist = float("inf")
        for obj in objectives[:8]:
            obj_hex = Hex.offset_to_axial(obj.coords[0], obj.coords[1])
            dist = start_hex.distance_to(obj_hex)
            if dist < best_dist:
                best_dist = dist
                best = obj
        return best, best_dist

class TacticalPlanner:
    MOVE_WEIGHTS = {
        "push_objective": {"objective": 12, "threat": -4, "support": 2, "capture": 8},
        "secure": {"objective": 8, "threat": -5, "support": 3, "capture": 3},
        "defend": {"objective": 4, "threat": -10, "support": 4, "capture": 2},
        "reinforce": {"objective": 9, "threat": -6, "support": 3, "capture": 2},
        "hold": {"objective": 2, "threat": -8, "support": 2, "capture": 1},
        "screen": {"objective": 6, "threat": -7, "support": 2, "capture": 2},
    }

    def deploy_ready_units(
        self,
        ctx: AIContext,
        allow_territory_wide: bool = False,
        country_filter: Optional[str] = None,
        invasion_deployment_active: bool = False,
        invasion_deployment_allegiance: Optional[str] = None,
        invasion_deployment_country_id: Optional[str] = None,
    ) -> int:
        deployed = 0
        ready_units = [
            u for u in ctx.game_state.units
            if getattr(u, "allegiance", None) == ctx.side
            and getattr(u, "status", None) == UnitState.READY
            and not getattr(u, "is_on_map", False)
        ]
        if country_filter:
            ready_units = [u for u in ready_units if getattr(u, "land", None) == country_filter]

        ready_units.sort(key=_unit_key)

        if ctx.side == HL:
            deployed += self._deploy_hl_dragon_pairs(
                ctx,
                ready_units,
                allow_territory_wide,
                country_filter,
                invasion_deployment_active,
                invasion_deployment_allegiance,
                invasion_deployment_country_id,
            )

        for unit in list(ready_units):
            if getattr(unit, "is_on_map", False):
                continue
            valid = ctx.game_state.get_valid_deployment_hexes(unit, allow_territory_wide=allow_territory_wide) or []
            if not valid:
                continue
            best_hex = max(
                valid,
                key=lambda coords: self._score_deployment_hex(ctx, unit, coords),
            )
            result = ctx.game_state.deployment_service.deploy_unit(
                unit,
                Hex.offset_to_axial(best_hex[0], best_hex[1]),
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if result.success:
                deployed += 1
        return deployed

    def _deploy_hl_dragon_pairs(
        self,
        ctx: AIContext,
        ready_units: List[object],
        allow_territory_wide: bool,
        country_filter: Optional[str],
        invasion_deployment_active: bool,
        invasion_deployment_allegiance: Optional[str],
        invasion_deployment_country_id: Optional[str],
    ) -> int:
        deployed = 0
        wings = [u for u in ready_units if getattr(u, "unit_type", None) == UnitType.WING]
        leaders = [u for u in ready_units if getattr(u, "unit_type", None) in (UnitType.HIGHLORD, UnitType.EMPEROR)]

        for wing in list(wings):
            if getattr(wing, "race", None) != UnitRace.DRAGON:
                continue
            commander = self._select_hl_dragon_commander(wing, leaders)
            if not commander:
                continue
            wing_valid = ctx.game_state.get_valid_deployment_hexes(wing, allow_territory_wide=allow_territory_wide) or []
            cmd_valid = ctx.game_state.get_valid_deployment_hexes(commander, allow_territory_wide=allow_territory_wide) or []
            if not wing_valid or not cmd_valid:
                continue
            cmd_set = {tuple(c) for c in cmd_valid}
            joint = [tuple(c) for c in wing_valid if tuple(c) in cmd_set]
            if not joint:
                continue
            best_hex = max(joint, key=lambda coords: self._score_deployment_hex(ctx, wing, coords))
            target_hex = Hex.offset_to_axial(best_hex[0], best_hex[1])
            wing_res = ctx.game_state.deployment_service.deploy_unit(
                wing,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if not wing_res.success:
                continue
            cmd_res = ctx.game_state.deployment_service.deploy_unit(
                commander,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if cmd_res.success:
                deployed += 2
                ready_units.remove(wing)
                ready_units.remove(commander)
                if wing in wings:
                    wings.remove(wing)
                if commander in leaders:
                    leaders.remove(commander)
        return deployed

    @staticmethod
    def _select_hl_dragon_commander(wing, leaders: List[object]) -> Optional[object]:
        flight = str(getattr(getattr(wing, "spec", None), "dragonflight", "") or "").strip().lower()
        same_flight = [
            l for l in leaders
            if getattr(l, "unit_type", None) == UnitType.HIGHLORD
            and str(getattr(getattr(l, "spec", None), "dragonflight", "") or "").strip().lower() == flight
        ]
        if same_flight:
            return sorted(same_flight, key=_unit_key)[0]
        emperors = [l for l in leaders if getattr(l, "unit_type", None) == UnitType.EMPEROR]
        if emperors:
            return sorted(emperors, key=_unit_key)[0]
        return None

    @staticmethod
    def _score_deployment_hex(ctx: AIContext, unit, coords: Tuple[int, int]) -> float:
        col, row = int(coords[0]), int(coords[1])
        threat = _overlay_value(ctx.overlays.get("threat"), col, row, 0.0)
        territory = ctx.overlays.get("territory")
        territory_val = territory.values.get((col, row)) if territory else None
        score = 0.0
        score -= threat * 3
        if territory_val == ctx.side:
            score += 6
        if territory_val == ctx.enemy:
            score -= 4

        loc = ctx.game_state.map.get_location(Hex.offset_to_axial(col, row))
        if loc:
            score += 5
            if getattr(loc, "is_capital", False):
                score += 8
        return score

    def execute_best_movement(self, ctx: AIContext, plan: StrategicPlan, missions: List[Mission], attempt_invasion=None) -> bool:
        if self._maybe_execute_transport_action(ctx, plan):
            return True

        actions = []
        for mission in missions:
            if not mission.group.mobile_units:
                continue
            action = self._best_move_for_mission(ctx, plan, mission)
            if action:
                actions.append(action)
        if not actions:
            return False

        actions.sort(key=lambda a: (a.score, a.group.power), reverse=True)
        best = actions[0]
        if best.score < 5:
            return False

        target_hex = best.target_hex
        if target_hex is None:
            return False

        decision = ctx.movement_service.evaluate_neutral_entry(target_hex)
        if decision.is_neutral_entry:
            if decision.blocked_message:
                return False
            if decision.confirmation_prompt and attempt_invasion:
                attempt_invasion(decision.country_id or "unknown")
                return True

        move_result = ctx.movement_service.move_units_to_hex(best.group.units, target_hex)
        if move_result.errors:
            return False
        return True

    def _best_move_for_mission(self, ctx: AIContext, plan: StrategicPlan, mission: Mission) -> Optional[TacticalAction]:
        group = mission.group
        move_range = ctx.movement_service.get_reachable_hexes(group.units)
        candidates = list(move_range.reachable_coords)
        if not candidates:
            return None
        current = group.hex.axial_to_offset()
        if current not in candidates:
            candidates.append(current)

        if len(candidates) > 80:
            candidates = candidates[:80]

        best_action = None
        for col, row in candidates:
            target_hex = Hex.offset_to_axial(col, row)
            score = self._score_move(ctx, plan, mission, target_hex)
            if best_action is None or score > best_action.score:
                best_action = TacticalAction(
                    kind="move",
                    group=group,
                    target_hex=target_hex,
                    score=score,
                    details=mission.mission_type,
                )
        return best_action

    def _score_move(self, ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        weights = self.MOVE_WEIGHTS.get(mission.mission_type, self.MOVE_WEIGHTS["screen"])
        col, row = target_hex.axial_to_offset()
        threat = _overlay_value(ctx.overlays.get("threat"), col, row, 0.0)
        friendly_power_overlay = ctx.overlays.get("ws_power") if ctx.side == WS else ctx.overlays.get("hl_power")
        support = _overlay_value(friendly_power_overlay, col, row, 0.0)
        territory = ctx.overlays.get("territory")
        territory_val = territory.values.get((col, row)) if territory else None

        score = 0.0
        if mission.target_hex is not None:
            distance = _hex_distance(target_hex, mission.target_hex)
            score += weights["objective"] * (max(0.0, 12.0 - distance))
        score += weights["threat"] * threat
        score += weights["support"] * support
        if territory_val == ctx.enemy:
            score += weights["capture"] * 6
        elif territory_val == ctx.side:
            score += 2

        loc = ctx.game_state.map.get_location(Hex.offset_to_axial(col, row))
        if loc and loc.occupier != ctx.side:
            score += 10
        return score

    def _maybe_execute_transport_action(self, ctx: AIContext, plan: StrategicPlan) -> bool:
        for unit in ctx.friendly_units:
            passengers = list(getattr(unit, "passengers", []) or [])
            if not passengers:
                continue
            if not getattr(unit, "position", None) or unit.position[0] is None:
                continue
            carrier_hex = Hex.offset_to_axial(*unit.position)
            if unit.is_wing() or unit.is_citadel():
                unboarded = self._unboard_all(ctx, unit, passengers)
                if unboarded:
                    return True
            else:
                if ctx.game_state.map.is_open_sea(carrier_hex):
                    continue
                if ctx.game_state.map.is_coastal(carrier_hex) or ctx.game_state.map.get_location(carrier_hex):
                    unboarded = self._unboard_all(ctx, unit, passengers)
                    if unboarded:
                        return True

        if not plan.transport_campaign:
            return False

        for unit in ctx.friendly_units:
            if getattr(unit, "unit_type", None) != UnitType.FLEET:
                continue
            if not getattr(unit, "position", None) or unit.position[0] is None:
                continue
            stack = ctx.game_state.map.get_units_in_hex(unit.position[0], unit.position[1])
            armies = [u for u in stack if getattr(u, "is_army", lambda: False)()]
            for army in armies:
                if ctx.game_state.board_unit(unit, army):
                    return True
        return False

    @staticmethod
    def _unboard_all(ctx: AIContext, carrier, passengers: List[object]) -> bool:
        moved = False
        for p in list(passengers):
            if ctx.game_state.unboard_unit(p):
                moved = True
        return moved

    def execute_best_combat(self, ctx: AIContext, plan: StrategicPlan, missions: List[Mission]) -> bool:
        actions = []
        board = ctx.game_state.map
        for mission in missions:
            group = mission.group
            if not group.units:
                continue
            if all(getattr(u, "attacked_this_turn", False) for u in group.units):
                continue
            for neighbor in group.hex.neighbors():
                defenders = board.get_units_in_hex(neighbor.q, neighbor.r)
                defenders = [u for u in defenders if getattr(u, "allegiance", None) == ctx.enemy and getattr(u, "is_on_map", False)]
                if not defenders:
                    continue
                if not ctx.game_state.can_units_attack_stack(group.units, defenders):
                    continue
                score = self._score_combat(ctx, plan, mission, group, defenders, neighbor)
                actions.append(TacticalAction(
                    kind="combat",
                    group=group,
                    target_hex=neighbor,
                    score=score,
                    details=mission.mission_type,
                ))

        if not actions:
            return False

        actions.sort(key=lambda a: (a.score, a.group.power), reverse=True)
        best = actions[0]
        if best.score < 20:
            return False

        attackers = [u for u in best.group.units if getattr(u, "is_on_map", False)]
        defenders_before = list(ctx.game_state.get_units_at(best.target_hex))
        resolution = ctx.game_state.resolve_combat(attackers, best.target_hex)
        show_combat_result_popup(
            ctx.game_state,
            title="AI Combat",
            attackers=attackers,
            defenders=defenders_before,
            resolution=resolution,
            context="ai_combat",
            target_hex=best.target_hex,
        )
        if resolution and resolution.get("advance_available"):
            ctx.game_state.advance_after_combat(attackers, best.target_hex)
        return True

    def _score_combat(self, ctx: AIContext, plan: StrategicPlan, mission: Mission, group: TaskGroup, defenders: List[object], target_hex: Hex) -> float:
        att_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in group.units if ctx.game_state.is_combat_unit(u))
        def_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in defenders if ctx.game_state.is_combat_unit(u))
        ratio = att_power / max(def_power, 1.0)
        score = ratio * 40

        col, row = target_hex.axial_to_offset()
        threat = _overlay_value(ctx.overlays.get("threat"), col, row, 0.0)
        score -= threat * 6

        if mission.objective and mission.objective.coords == (col, row):
            score += mission.objective.value
        loc = ctx.game_state.map.get_location(Hex.offset_to_axial(col, row))
        if loc and loc.occupier == ctx.enemy:
            score += 12
        if plan.posture == "offensive":
            score += 8
        elif plan.posture == "defensive":
            score -= 6
        return score

class BaselineAIPlayer:
    def __init__(self, game_state, movement_service, diplomacy_service):
        self.game_state = game_state
        self.movement_service = movement_service
        self.diplomacy_service = diplomacy_service
        self._movement_phase_key = None
        self._combat_phase_key = None
        self._unit_last_position: Dict[Tuple[str, int], Tuple[int, int]] = {}
        self._failed_combat_targets = defaultdict(set)
        self._strategic = StrategicPlanner()
        self._operational = OperationalPlanner()
        self._tactical = TacticalPlanner()

    # ---------- Deployment ----------
    def deploy_all_ready_units(
        self,
        side: str,
        allow_territory_wide: bool = False,
        country_filter: str | None = None,
        invasion_deployment_active: bool = False,
        invasion_deployment_allegiance: str | None = None,
        invasion_deployment_country_id: str | None = None,
    ) -> int:
        ctx = self._build_context(side)
        plan = self._strategic.build_plan(ctx)
        deployed = self._tactical.deploy_ready_units(
            ctx,
            allow_territory_wide=allow_territory_wide,
            country_filter=country_filter,
            invasion_deployment_active=invasion_deployment_active,
            invasion_deployment_allegiance=invasion_deployment_allegiance,
            invasion_deployment_country_id=invasion_deployment_country_id,
        )
        self._log(f"deploy: {deployed} units ({plan.posture})")
        return deployed

    # ---------- Replacements ----------
    def process_replacements(self, side: str) -> tuple[int, int]:
        conscriptions = self._apply_conscriptions(side)
        deployed = self.deploy_all_ready_units(side)
        return conscriptions, deployed

    def _apply_conscriptions(self, side: str) -> int:
        conscriptions = 0
        while True:
            reserve_units = [
                u for u in self.game_state.units
                if getattr(u, "allegiance", None) == side
                and getattr(u, "status", None) == UnitState.RESERVE
            ]
            if len(reserve_units) < 2:
                break

            groups = defaultdict(list)
            for unit in reserve_units:
                key = self.game_state.get_replacement_group_key(unit)
                groups[key].append(unit)

            pair_found = False
            for key in sorted(groups.keys(), key=lambda x: str(x)):
                units = groups[key]
                if len(units) < 2:
                    continue
                units = sorted(units, key=self._conscription_sort_key, reverse=True)
                kept_unit = units[0]
                discarded_unit = units[1]
                if not self.game_state.can_conscript_pair(kept_unit, discarded_unit):
                    continue
                self.game_state.apply_conscription(kept_unit, discarded_unit)
                conscriptions += 1
                pair_found = True
                break

            if not pair_found:
                break
        return conscriptions

    @staticmethod
    def _conscription_sort_key(unit):
        return (
            int(getattr(unit, "combat_rating", 0) or 0),
            int(getattr(unit, "movement", 0) or 0),
            str(getattr(unit, "id", "")),
            -int(getattr(unit, "ordinal", 1)),
        )

    # ---------- Activation ----------
    def perform_activation(self, side: str) -> tuple[bool, str | None]:
        ctx = self._build_context(side)
        plan = self._strategic.build_plan(ctx)
        neutrals = [c for c in self.game_state.countries.values() if getattr(c, "allegiance", None) == NEUTRAL]
        if not neutrals:
            return False, None

        best = None
        best_score = float("-inf")
        for country in neutrals:
            attempt = self.diplomacy_service.build_activation_attempt(country.id)
            if not attempt:
                continue
            alignment = getattr(country, "alignment", (0, 0))
            align_score = float(alignment[1] if side == HL else alignment[0]) * 10
            objective_score = 0.0
            for obj in plan.objectives[:8]:
                if obj.country_id == country.id:
                    objective_score += obj.value
            score = attempt.target_rating * 12 + align_score + objective_score
            if score > best_score:
                best_score = score
                best = country

        if not best:
            return False, None

        attempt = self.diplomacy_service.build_activation_attempt(best.id)
        if not attempt:
            return False, None
        bonus = int(getattr(attempt, "event_activation_bonus", 0) or 0)
        roll = self.diplomacy_service.roll_activation(attempt.target_rating, roll_bonus=bonus)
        if not roll.success:
            return False, best.id

        self.diplomacy_service.activate_country(best.id, side)
        deployed = self.deploy_all_ready_units(side, allow_territory_wide=True, country_filter=best.id)
        self._log(f"activation success: {best.id} deployed={deployed}")
        return True, best.id

    # ---------- Assets ----------
    def assign_assets(self, side: str) -> int:
        ctx = self._build_context(side)
        player = self.game_state.players.get(side)
        if not player:
            return 0
        assets = [
            a for a in getattr(player, "assets", {}).values()
            if getattr(a, "is_equippable", False)
            and getattr(a, "assigned_to", None) is None
        ]
        if not assets:
            return 0

        units = [u for u in ctx.friendly_units if getattr(u, "is_on_map", False)]
        if not units:
            return 0

        assigned = 0
        for asset in sorted(assets, key=lambda a: str(getattr(a, "id", ""))):
            candidates = [u for u in units if asset.can_equip(u)]
            if not candidates:
                continue
            best = max(candidates, key=lambda u: self._score_asset_target(ctx, asset, u))
            asset.apply_to(best)
            if getattr(asset, "assigned_to", None) is best:
                assigned += 1
        return assigned

    @staticmethod
    def _score_asset_target(ctx: AIContext, asset, unit) -> float:
        score = float(getattr(unit, "combat_rating", 0) or 0) * 2
        score += float(getattr(unit, "tactical_rating", 0) or 0)
        if getattr(unit, "is_leader", lambda: False)():
            score += 6
        if getattr(unit, "is_army", lambda: False)():
            score += 4
        if unit.is_wing():
            score += 2
        if getattr(unit, "position", None) and unit.position[0] is not None:
            col, row = unit.position
            threat = _overlay_value(ctx.overlays.get("threat"), col, row, 0.0)
            score += threat
        return score

    # ---------- Movement ----------
    def execute_best_movement(self, side: str, attempt_invasion=None) -> bool:
        ctx = self._build_context(side)
        plan = self._strategic.build_plan(ctx)
        groups = self._operational.build_task_groups(ctx)
        missions = self._operational.build_missions(ctx, plan, groups)
        moved = self._tactical.execute_best_movement(ctx, plan, missions, attempt_invasion=attempt_invasion)
        if moved:
            self._log(f"movement: executed ({plan.posture})")
        return moved

    # ---------- Combat ----------
    def execute_best_combat(self, side: str) -> bool:
        ctx = self._build_context(side)
        plan = self._strategic.build_plan(ctx)
        groups = self._operational.build_task_groups(ctx)
        missions = self._operational.build_missions(ctx, plan, groups)
        fought = self._tactical.execute_best_combat(ctx, plan, missions)
        if fought:
            self._log("combat: executed")
        return fought

    # ---------- Context ----------
    def _build_context(self, side: str) -> AIContext:
        enemy = _enemy_of(side)
        overlays = {
            "control": self.game_state.get_overlay("control"),
            "territory": self.game_state.get_overlay("territory"),
            "supply": self.game_state.get_overlay("supply"),
            "ws_power": self.game_state.get_overlay("ws_power"),
            "hl_power": self.game_state.get_overlay("hl_power"),
            "threat": self.game_state.get_overlay("threat"),
        }
        control_facts = self.game_state.get_control_facts()
        objectives = self._collect_objectives(side)
        friendly_units = [u for u in self.game_state.units if getattr(u, "allegiance", None) == side and getattr(u, "is_on_map", False)]
        enemy_units = [u for u in self.game_state.units if getattr(u, "allegiance", None) == enemy and getattr(u, "is_on_map", False)]

        return AIContext(
            game_state=self.game_state,
            movement_service=self.movement_service,
            diplomacy_service=self.diplomacy_service,
            side=side,
            enemy=enemy,
            turn=int(getattr(self.game_state, "turn", 0) or 0),
            phase=getattr(self.game_state, "phase", None),
            control_facts=control_facts,
            overlays=overlays,
            objectives=objectives,
            friendly_units=friendly_units,
            enemy_units=enemy_units,
        )

    def _collect_objectives(self, side: str) -> List[Objective]:
        raw_victory = (getattr(self.game_state.scenario_spec, "victory_conditions", {}) or {}).get(side, {})
        location_targets, country_targets = self._extract_victory_targets(raw_victory)
        objectives: List[Objective] = []
        for country in self.game_state.countries.values():
            for loc in country.locations.values():
                if not loc.coords:
                    continue
                value = 10.0
                if loc.is_capital:
                    value += 40
                if loc.loc_type == LocType.FORTRESS.value:
                    value += 15
                if loc.loc_type == LocType.TEMPLE.value:
                    value += 20
                if loc.loc_type == LocType.PORT.value:
                    value += 8
                if loc.id in location_targets:
                    value += 50
                if country.id in country_targets:
                    value += 25
                if loc.occupier != side:
                    value += 10
                objectives.append(Objective(
                    id=loc.id,
                    coords=(loc.coords[0], loc.coords[1]),
                    owner=loc.occupier,
                    value=value,
                    is_capital=bool(loc.is_capital),
                    loc_type=loc.loc_type,
                    country_id=country.id,
                ))
        objectives.sort(key=lambda o: (o.value, o.owner != side), reverse=True)
        return objectives

    def _extract_victory_targets(self, raw: Any) -> Tuple[set[str], set[str]]:
        locations = set()
        countries = set()

        def walk(node: Any):
            if isinstance(node, dict):
                if "all" in node:
                    for child in node.get("all", []) or []:
                        walk(child)
                if "any" in node:
                    for child in node.get("any", []) or []:
                        walk(child)
                if "type" in node:
                    node_type = str(node.get("type"))
                    if node_type in {"capture_location", "prevent_location_captured"}:
                        loc_id = _slugify(node.get("location", ""))
                        if loc_id:
                            locations.add(loc_id)
                    if node_type in {"conquer_country", "prevent_country_conquered"}:
                        country_id = _slugify(node.get("country", ""))
                        if country_id:
                            countries.add(country_id)
                return
            if isinstance(node, list):
                for child in node:
                    walk(child)

        if isinstance(raw, dict):
            walk(raw.get("major"))
            walk(raw.get("minor"))
            walk(raw.get("marginal"))
        elif isinstance(raw, list):
            walk(raw)
        return locations, countries

    def _log(self, msg: str):
        print(f"AI[{self.game_state.active_player}] {msg}")
