
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Set

from src.content import loader
from src.content.config import AI_STANCE_DATA
from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import UnitType, UnitState, LocType, UnitRace, HexsideType
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


def _task_group_key(group) -> Tuple[Tuple[str, int], ...]:
    return tuple(sorted(_unit_key(u) for u in group.units))


def _hex_distance(a: Hex, b: Hex) -> int:
    return a.distance_to(b)


def _overlay_value(overlay, col: int, row: int, default: float = 0.0) -> float:
    if overlay is None:
        return default
    return float(overlay.values.get((col, row), default) or default)


def _slugify(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")

_AI_STANCE_CACHE: Optional[Dict[str, Dict[str, str]]] = None
_VICTORY_CATEGORY_PRIORITY = [
    "capture",
    "conquer",
    "control",
    "destroy",
    "prevent",
    "escape",
    "survive",
]


def _load_ai_stance_matrix() -> Dict[str, Dict[str, str]]:
    global _AI_STANCE_CACHE
    if _AI_STANCE_CACHE is None:
        _AI_STANCE_CACHE = loader.load_ai_stance_csv(AI_STANCE_DATA)
    return _AI_STANCE_CACHE or {}


def _victory_category_for_type(node_type: str) -> Optional[str]:
    key = str(node_type or "").strip().lower()
    if not key:
        return None
    if key.startswith("capture"):
        return "capture"
    if key.startswith("conquer"):
        return "conquer"
    if key.startswith("control"):
        return "control"
    if key.startswith("destroy"):
        return "destroy"
    if key.startswith("prevent"):
        return "prevent"
    if key.startswith("escape"):
        return "escape"
    if key.startswith("survive"):
        return "survive"
    return None


def _extract_victory_metadata(raw: Any) -> Dict[str, Any]:
    categories_by_tier = {"major": [], "minor": [], "marginal": []}
    location_targets: Set[str] = set()
    country_targets: Set[str] = set()
    location_deadlines: Dict[str, int] = {}
    country_deadlines: Dict[str, int] = {}
    overall_deadline: Optional[int] = None

    def record_deadline(deadline: Optional[int], bucket: Dict[str, int], key: str):
        nonlocal overall_deadline
        if deadline is None:
            return
        bucket[key] = min(deadline, bucket.get(key, deadline))
        overall_deadline = min(deadline, overall_deadline) if overall_deadline is not None else deadline

    def walk(node: Any, tier: str):
        nonlocal overall_deadline
        if isinstance(node, dict):
            if "all" in node:
                for child in node.get("all", []) or []:
                    walk(child, tier)
            if "any" in node:
                for child in node.get("any", []) or []:
                    walk(child, tier)
            if "type" in node:
                node_type = str(node.get("type", "") or "")
                category = _victory_category_for_type(node_type)
                if category:
                    categories_by_tier[tier].append(category)
                deadline = node.get("by_turn")
                try:
                    deadline = int(deadline) if deadline is not None else None
                except Exception:
                    deadline = None
                if node_type in {"capture_location", "prevent_location_captured"}:
                    loc_id = _slugify(node.get("location", ""))
                    if loc_id:
                        location_targets.add(loc_id)
                        record_deadline(deadline, location_deadlines, loc_id)
                elif node_type in {"conquer_country", "prevent_country_conquered"}:
                    country_id = _slugify(node.get("country", ""))
                    if country_id:
                        country_targets.add(country_id)
                        record_deadline(deadline, country_deadlines, country_id)
                elif deadline is not None:
                    overall_deadline = min(deadline, overall_deadline) if overall_deadline is not None else deadline
            return
        if isinstance(node, list):
            for child in node:
                walk(child, tier)

    if isinstance(raw, dict):
        for tier in ("major", "minor", "marginal"):
            if tier in raw:
                walk(raw.get(tier), tier)
    elif isinstance(raw, list):
        walk(raw, "minor")

    def pick_primary_category() -> Optional[str]:
        for tier in ("major", "minor", "marginal"):
            cats = categories_by_tier.get(tier) or []
            if not cats:
                continue
            counts: Dict[str, int] = {}
            for cat in cats:
                counts[cat] = counts.get(cat, 0) + 1
            best = sorted(
                counts.items(),
                key=lambda item: (item[1], -_VICTORY_CATEGORY_PRIORITY.index(item[0])),
                reverse=True,
            )
            return best[0][0] if best else None
        return None

    return {
        "primary_category": pick_primary_category(),
        "location_targets": location_targets,
        "country_targets": country_targets,
        "location_deadlines": location_deadlines,
        "country_deadlines": country_deadlines,
        "deadline": overall_deadline,
    }


def _determine_offensive_side(hl_category: Optional[str], ws_category: Optional[str]) -> Optional[str]:
    if not hl_category or not ws_category:
        return None
    matrix = _load_ai_stance_matrix()
    row = matrix.get(str(hl_category).lower(), {})
    entry = row.get(str(ws_category).lower())
    if entry == "HL":
        return HL
    if entry == "WS":
        return WS
    return None


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
    main_objective: Optional[Objective] = None
    objective_deadline_turn: Optional[int] = None
    urgency_score: float = 0.0
    offensive_side: Optional[str] = None
    must_act: bool = False
    victory_category: Optional[str] = None
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
    moved_task_groups: Optional[set] = None
    failed_combat_targets: Optional[Set[Tuple[int, int]]] = None


class StrategicPlanner:
    def build_plan(self, ctx: AIContext) -> StrategicPlan:
        posture, notes, offensive_side, main_objective, deadline_turn, urgency_score, must_act, victory_category = self._choose_posture(ctx)
        objectives = self._prioritize_objectives(ctx)
        transport_campaign = self._should_use_transport(ctx, objectives, offensive_side, main_objective)
        invasion_target = self._choose_invasion_target(ctx, objectives)
        return StrategicPlan(
            posture=posture,
            objectives=objectives,
            transport_campaign=transport_campaign,
            invasion_target=invasion_target,
            main_objective=main_objective,
            objective_deadline_turn=deadline_turn,
            urgency_score=urgency_score,
            offensive_side=offensive_side,
            must_act=must_act,
            victory_category=victory_category,
            notes=notes,
        )

    def _choose_posture(self, ctx: AIContext) -> Tuple[str, List[str], Optional[str], Optional[Objective], Optional[int], float, bool, Optional[str]]:
        notes = []
        victory_conditions = getattr(ctx.game_state.scenario_spec, "victory_conditions", {}) or {}
        hl_meta = _extract_victory_metadata(victory_conditions.get(HL, {}))
        ws_meta = _extract_victory_metadata(victory_conditions.get(WS, {}))
        hl_category = hl_meta.get("primary_category")
        ws_category = ws_meta.get("primary_category")
        offensive_side = _determine_offensive_side(hl_category, ws_category)
        side_meta = hl_meta if ctx.side == HL else ws_meta
        victory_category = side_meta.get("primary_category")

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
        base_posture = "balanced"
        if offensive_side == ctx.side:
            base_posture = "offensive"
        elif offensive_side and offensive_side != ctx.side:
            base_posture = "defensive"

        main_objective, deadline_turn = self._select_main_objective(ctx, side_meta, offensive_side)
        urgency_score = self._compute_urgency(ctx, deadline_turn, offensive_side == ctx.side)
        posture = self._modulate_posture(
            ctx,
            base_posture,
            ratio,
            friendly_hexes,
            enemy_hexes,
            urgency_score,
        )
        must_act = bool(offensive_side == ctx.side and (urgency_score >= 0.5 or base_posture == "offensive"))

        end_turn = int(getattr(ctx.game_state.scenario_spec, "end_turn", 0) or 0)
        if end_turn:
            turns_left = max(0, end_turn - ctx.turn)
            if turns_left <= 2:
                victory_eval = getattr(ctx.game_state, "victory_evaluator", None)
                if victory_eval:
                    status = victory_eval.evaluate()
                    points = status.minor_points
                    if points.get(ctx.side, 0) < points.get(ctx.enemy, 0):
                        if base_posture == "offensive":
                            posture = "desperate_offensive"
                        else:
                            posture = "offensive"
                        notes.append("late-game push")
        notes.append(f"power_ratio={ratio:.2f}")
        notes.append(f"territory={friendly_hexes}:{enemy_hexes}")
        if offensive_side:
            notes.append(f"offensive_side={offensive_side}")
        if victory_category:
            notes.append(f"victory_category={victory_category}")
        if deadline_turn:
            notes.append(f"deadline_turn={deadline_turn}")
        notes.append(f"urgency={urgency_score:.2f}")
        return posture, notes, offensive_side, main_objective, deadline_turn, urgency_score, must_act, victory_category

    def _select_main_objective(self, ctx: AIContext, side_meta: Dict[str, Any], offensive_side: Optional[str]):
        objectives = list(ctx.objectives or [])
        location_targets = side_meta.get("location_targets", set()) or set()
        country_targets = side_meta.get("country_targets", set()) or set()
        location_deadlines = side_meta.get("location_deadlines", {}) or {}
        country_deadlines = side_meta.get("country_deadlines", {}) or {}
        deadline_turn = side_meta.get("deadline")

        candidates = [
            obj for obj in objectives
            if obj.id in location_targets or (obj.country_id and obj.country_id in country_targets)
        ]
        if not candidates and offensive_side == ctx.side:
            candidates = [obj for obj in objectives if obj.owner != ctx.side]
        if not candidates:
            candidates = objectives

        if not candidates:
            return None, deadline_turn

        main_objective = max(
            candidates,
            key=lambda o: (o.owner != ctx.side, o.value, o.is_capital),
        )
        if main_objective.id in location_deadlines:
            deadline_turn = min(deadline_turn, location_deadlines[main_objective.id]) if deadline_turn else location_deadlines[main_objective.id]
        elif main_objective.country_id in country_deadlines:
            deadline_turn = min(deadline_turn, country_deadlines[main_objective.country_id]) if deadline_turn else country_deadlines[main_objective.country_id]
        return main_objective, deadline_turn

    def _compute_urgency(self, ctx: AIContext, deadline_turn: Optional[int], is_offensive_side: bool) -> float:
        if deadline_turn is not None:
            turns_left = deadline_turn - ctx.turn
            if turns_left <= 0:
                return 1.0
            if turns_left <= 2:
                return 0.9
            if turns_left <= 4:
                return 0.7
            if turns_left <= 6:
                return 0.5
            return 0.3
        end_turn = int(getattr(ctx.game_state.scenario_spec, "end_turn", 0) or 0)
        if end_turn:
            turns_left = max(0, end_turn - ctx.turn)
            if turns_left <= 2:
                return 0.6 if is_offensive_side else 0.4
            if turns_left <= 4:
                return 0.4 if is_offensive_side else 0.2
        return 0.2 if is_offensive_side else 0.1

    def _modulate_posture(
        self,
        ctx: AIContext,
        base_posture: str,
        ratio: float,
        friendly_hexes: int,
        enemy_hexes: int,
        urgency_score: float,
    ) -> str:
        if base_posture == "offensive":
            if urgency_score >= 0.8:
                return "desperate_offensive"
            if ratio < 0.8 or friendly_hexes < enemy_hexes * 0.75:
                return "cautious_offensive"
            return "offensive"
        if base_posture == "defensive":
            if ratio > 1.3 and urgency_score < 0.4:
                return "balanced"
            return "defensive"

        if ratio < 0.85 or friendly_hexes < enemy_hexes * 0.8:
            return "defensive"
        if ratio > 1.2 or friendly_hexes > enemy_hexes * 1.2:
            return "offensive"
        return "balanced"

    def _prioritize_objectives(self, ctx: AIContext) -> List[Objective]:
        objectives = list(ctx.objectives)
        objectives.sort(key=lambda o: (o.value, o.owner != ctx.side, o.is_capital), reverse=True)
        return objectives

    def _should_use_transport(
        self,
        ctx: AIContext,
        objectives: List[Objective],
        offensive_side: Optional[str],
        main_objective: Optional[Objective],
    ) -> bool:
        if offensive_side != ctx.side:
            return False
        fleets = [
            u for u in ctx.game_state.units
            if getattr(u, "allegiance", None) == ctx.side
            and getattr(u, "unit_type", None) == UnitType.FLEET
            and (
                getattr(u, "is_on_map", False)
                or getattr(u, "status", None) == UnitState.READY
            )
        ]
        if not fleets:
            return False
        if not objectives:
            return False

        target_objectives = []
        if main_objective:
            target_objectives.append(main_objective)
        target_objectives.extend([o for o in objectives if o.owner != ctx.side and o is not main_objective][:3])
        if not target_objectives:
            return False

        ground_units = [
            u for u in ctx.game_state.units
            if getattr(u, "allegiance", None) == ctx.side
            and getattr(u, "is_army", lambda: False)()
            and getattr(u, "unit_type", None) not in (UnitType.WING, UnitType.FLEET)
            and (
                getattr(u, "is_on_map", False)
                or getattr(u, "status", None) == UnitState.READY
            )
        ]
        if not ground_units:
            return False

        starts: List[Hex] = []
        for u in ground_units:
            if getattr(u, "is_on_map", False) and getattr(u, "position", None) and u.position[0] is not None:
                starts.append(Hex.offset_to_axial(*u.position))
                continue
            valid = ctx.game_state.get_valid_deployment_hexes(u, allow_territory_wide=False) or []
            for col, row in sorted(valid)[:6]:
                starts.append(Hex.offset_to_axial(int(col), int(row)))
        if not starts:
            return False
        all_start_coastal = all(ctx.game_state.map.is_coastal(h) or ctx.game_state.map.get_location(h) for h in starts)

        for obj in target_objectives:
            target_hex = Hex.offset_to_axial(obj.coords[0], obj.coords[1])
            reachable = any(self._is_plausibly_land_reachable(ctx, s, target_hex, max_depth=18) for s in starts[:10])
            if not reachable:
                return True
            if all_start_coastal and ctx.game_state.map.is_coastal(target_hex):
                min_land_dist = min(s.distance_to(target_hex) for s in starts)
                if min_land_dist >= 12:
                    return True
        return False

    @staticmethod
    def _is_plausibly_land_reachable(ctx: AIContext, start_hex: Hex, target_hex: Hex, max_depth: int = 18) -> bool:
        if start_hex == target_hex:
            return True
        board = ctx.game_state.map
        from collections import deque

        frontier = deque([(start_hex, 0)])
        visited = {(start_hex.q, start_hex.r)}
        while frontier:
            current, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            for neighbor in current.neighbors():
                key = (neighbor.q, neighbor.r)
                if key in visited:
                    continue
                col, row = neighbor.axial_to_offset()
                if not ctx.game_state.is_hex_in_bounds(col, row):
                    continue
                if not ctx.game_state.can_control_probe_project_across_hexside(current, neighbor, allegiance=ctx.side):
                    continue
                if board.has_enemy_army(neighbor, ctx.side):
                    continue
                if neighbor == target_hex:
                    return True
                visited.add(key)
                frontier.append((neighbor, depth + 1))
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
            # Structural split by role/mobility:
            # - Ground: armies + leaders (leaders are never isolated as standalone groups)
            # - Air: wings + citadels
            # - Fleet: fleets only
            armies = [u for u in stack if getattr(u, "is_army", lambda: False)() and getattr(u, "unit_type", None) != UnitType.FLEET]
            leaders = [
                u for u in stack
                if hasattr(u, "is_leader")
                and u.is_leader()
                and getattr(u, "transport_host", None) is None
            ]
            air_units = [u for u in stack if getattr(u, "is_wing", lambda: False)() or getattr(u, "is_citadel", lambda: False)()]
            fleets = [u for u in stack if getattr(u, "unit_type", None) == UnitType.FLEET]

            role_groups: List[List[object]] = []
            if armies:
                role_groups.append(armies + leaders)
            if air_units:
                role_groups.append(air_units)
            if fleets:
                role_groups.append(fleets)

            for role_units in role_groups:
                combat_units = [u for u in role_units if ctx.game_state.is_combat_unit(u)]
                if not combat_units:
                    continue
                power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in combat_units)
                has_fleet = any(getattr(u, "unit_type", None) == UnitType.FLEET for u in role_units)
                has_air = any(getattr(u, "is_wing", lambda: False)() or getattr(u, "is_citadel", lambda: False)() for u in role_units)
                has_army = any(getattr(u, "is_army", lambda: False)() and getattr(u, "unit_type", None) != UnitType.FLEET for u in role_units)
                mobile_units = [
                    u for u in role_units
                    if getattr(u, "transport_host", None) is None
                    and float(getattr(u, "movement_points", 0) or 0) > 0
                ]
                groups.append(TaskGroup(
                    units=role_units,
                    hex=hex_obj,
                    power=power,
                    has_army=has_army,
                    has_wing=has_air,
                    has_fleet=has_fleet,
                    mobile_units=mobile_units,
                ))
        return groups

    def build_missions(self, ctx: AIContext, plan: StrategicPlan, groups: List[TaskGroup]) -> List[Mission]:
        missions = []
        threat = ctx.overlays.get("threat")
        locations = self._collect_location_map(ctx)
        offensive = plan.offensive_side == ctx.side
        main_objective = plan.main_objective
        main_hex = Hex.offset_to_axial(main_objective.coords[0], main_objective.coords[1]) if main_objective else None

        main_effort_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        support_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()

        if offensive and main_hex:
            # Get all mobile ground-capable groups for main effort consideration
            candidates = [
                g for g in groups
                if g.mobile_units and (g.has_army or g.has_wing)
            ]
            candidates.sort(key=lambda g: (-g.power, g.hex.distance_to(main_hex)))

            if candidates:
                # Offensive force concentration: commit MAJORITY of mobile force to main effort
                # Scale by urgency and posture - high urgency means more commitment
                is_high_urgency = plan.urgency_score >= 0.5 or plan.must_act
                is_desperate = plan.posture == "desperate_offensive"

                if is_desperate:
                    # Desperate offensive: commit 75-80% of force
                    main_count = max(3, (len(candidates) * 75) // 100)
                    support_count = max(2, (len(candidates) * 15) // 100)
                elif is_high_urgency:
                    # High urgency: commit 65-70% of force
                    main_count = max(3, (len(candidates) * 65) // 100)
                    support_count = max(2, (len(candidates) * 15) // 100)
                elif plan.posture in ("offensive", "cautious_offensive"):
                    # Standard offensive: commit 55-60% of force
                    main_count = max(2, (len(candidates) * 55) // 100)
                    support_count = max(1, (len(candidates) * 15) // 100)
                else:
                    # Balanced: conservative but still meaningful commitment
                    main_count = max(2, (len(candidates) * 45) // 100)
                    support_count = max(1, (len(candidates) * 15) // 100)

                # Clamp to available candidates
                total_commit = min(len(candidates), main_count + support_count)
                main_count = min(main_count, total_commit)
                support_count = min(support_count, total_commit - main_count)

                main_effort_group_keys = {_task_group_key(g) for g in candidates[:main_count]}
                support_group_keys = {_task_group_key(g) for g in candidates[main_count:main_count + support_count]}

        for group in groups:
            col, row = group.hex.axial_to_offset()
            loc = locations.get((col, row))
            local_threat = _overlay_value(threat, col, row, 0.0)
            group_key = _task_group_key(group)

            if offensive and plan.transport_campaign and main_hex:
                if group.has_fleet:
                    landing_hex = self._best_landing_hex_for_objective(ctx, main_hex, fallback=group.hex)
                    missions.append(Mission(
                        group=group,
                        mission_type="transport_main_effort",
                        target_hex=landing_hex,
                        objective=main_objective,
                        priority=95 + plan.urgency_score * 20 + group.power * 0.5,
                    ))
                    continue
                if group.has_army and self._group_needs_embarkation(ctx, group, main_hex):
                    embark_hex = self._best_embark_hex(ctx, group, main_hex)
                    missions.append(Mission(
                        group=group,
                        mission_type="embark_main_effort",
                        target_hex=embark_hex,
                        objective=main_objective,
                        priority=145 + plan.urgency_score * 30 + group.power * 0.8,
                    ))
                    continue

            # Priority 1: Main effort and support missions (offensive only)
            if offensive and main_hex:
                if group_key in main_effort_group_keys:
                    missions.append(Mission(
                        group=group,
                        mission_type="main_effort_attack",
                        target_hex=main_hex,
                        objective=main_objective,
                        priority=150 + plan.urgency_score * 50 + group.power,
                    ))
                    continue
                if group_key in support_group_keys:
                    missions.append(Mission(
                        group=group,
                        mission_type="support_main_effort",
                        target_hex=main_hex,
                        objective=main_objective,
                        priority=110 + plan.urgency_score * 30 + group.power * 0.7,
                    ))
                    continue

            # Priority 2: Defend threatened key locations (minimum defense)
            if loc and loc.occupier == ctx.side and local_threat >= 2.0:
                mission_type = "defend_key_location" if offensive else "defend"
                missions.append(Mission(
                    group=group,
                    mission_type=mission_type,
                    target_hex=group.hex,
                    objective=None,
                    priority=(70 if offensive else 80) + local_threat * 10,
                ))
                continue

            # Priority 3: Objective-driven missions
            objective, distance = self._nearest_objective(group.hex, plan.objectives)
            if plan.posture == "defensive" and not offensive:
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
                    if (
                        offensive
                        and objective.owner != ctx.side
                        and self._should_prepare_assault(ctx, plan, group, objective)
                    ):
                        mission_type = "prepare_assault"
                    missions.append(Mission(
                        group=group,
                        mission_type=mission_type,
                        target_hex=Hex.offset_to_axial(objective.coords[0], objective.coords[1]),
                        objective=objective,
                        priority=max(20.0, objective.value - distance * 1.5)
                        + (15 if offensive and objective.owner != ctx.side else 0),
                    ))
                else:
                    missions.append(Mission(
                        group=group,
                        mission_type="reserve_screen" if offensive else "screen",
                        target_hex=group.hex,
                        objective=None,
                        priority=12 if offensive else 15,
                    ))

        missions.sort(key=lambda m: (m.priority, m.group.power), reverse=True)
        return missions

    @staticmethod
    def _group_needs_embarkation(ctx: AIContext, group: TaskGroup, target_hex: Hex) -> bool:
        if group.has_fleet or not group.has_army:
            return False
        # bounded land reachability probe from current group hex
        from collections import deque

        frontier = deque([(group.hex, 0)])
        visited = {(group.hex.q, group.hex.r)}
        while frontier:
            current, depth = frontier.popleft()
            if depth >= 14:
                continue
            for nxt in current.neighbors():
                key = (nxt.q, nxt.r)
                if key in visited:
                    continue
                col, row = nxt.axial_to_offset()
                if not ctx.game_state.is_hex_in_bounds(col, row):
                    continue
                if not ctx.game_state.can_control_probe_project_across_hexside(current, nxt, allegiance=ctx.side):
                    continue
                if ctx.game_state.map.has_enemy_army(nxt, ctx.side):
                    continue
                if nxt == target_hex:
                    return False
                visited.add(key)
                frontier.append((nxt, depth + 1))
        return True

    @staticmethod
    def _best_landing_hex_for_objective(ctx: AIContext, main_hex: Hex, fallback: Hex) -> Hex:
        board = ctx.game_state.map
        best = None
        best_score = float("-inf")
        for col in range(int(getattr(board, "width", 0) or 0)):
            for row in range(int(getattr(board, "height", 0) or 0)):
                h = Hex.offset_to_axial(col, row)
                if not board.is_coastal(h) and not board.get_location(h):
                    continue
                score = -h.distance_to(main_hex) * 2.0
                territory = ctx.overlays.get("territory")
                tval = territory.values.get((col, row)) if territory else None
                if tval == ctx.enemy:
                    score += 8.0
                elif tval == ctx.side:
                    score += 3.0
                if best is None or score > best_score:
                    best = h
                    best_score = score
        return best or fallback

    @staticmethod
    def _best_embark_hex(ctx: AIContext, group: TaskGroup, main_hex: Hex) -> Hex:
        fleet_hexes = []
        for u in ctx.friendly_units:
            if getattr(u, "unit_type", None) != UnitType.FLEET:
                continue
            if not getattr(u, "is_on_map", False):
                continue
            if not getattr(u, "position", None) or u.position[0] is None:
                continue
            fleet_hexes.append(Hex.offset_to_axial(*u.position))
        if not fleet_hexes:
            return group.hex
        return min(fleet_hexes, key=lambda h: (group.hex.distance_to(h), h.distance_to(main_hex)))

    @staticmethod
    def _should_prepare_assault(ctx: AIContext, plan: StrategicPlan, group: TaskGroup, objective: Objective) -> bool:
        target_hex = Hex.offset_to_axial(objective.coords[0], objective.coords[1])
        distance = group.hex.distance_to(target_hex)
        if distance > 6:
            return False
        if distance <= 1:
            return False
        if group.has_fleet:
            return False

        defenders = [
            u for u in ctx.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
            if getattr(u, "allegiance", None) == ctx.enemy and getattr(u, "is_on_map", False)
        ]
        defender_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in defenders
            if ctx.game_state.is_combat_unit(u)
        )
        if defender_power <= 0:
            return False

        # Offensive groups near important fronts should stage when currently underpowered,
        # unless must-act pressure requires immediate risk acceptance.
        must_force = bool(plan.must_act or (plan.objective_deadline_turn is not None and plan.objective_deadline_turn - ctx.turn <= 2))
        if must_force:
            return False
        return group.power < defender_power * 1.15

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
        "prepare_assault": {"objective": 11, "threat": -5, "support": 5, "capture": 3},
        "embark_main_effort": {"objective": 12, "threat": -5, "support": 5, "capture": 3},
        "transport_main_effort": {"objective": 14, "threat": -4, "support": 4, "capture": 7},
        "move_to_landing_area": {"objective": 12, "threat": -4, "support": 3, "capture": 6},
        "main_effort_attack": {"objective": 16, "threat": -5, "support": 4, "capture": 10},
        "support_main_effort": {"objective": 10, "threat": -4, "support": 5, "capture": 6},
        "secure": {"objective": 8, "threat": -5, "support": 3, "capture": 3},
        "defend": {"objective": 4, "threat": -10, "support": 4, "capture": 2},
        "defend_key_location": {"objective": 4, "threat": -10, "support": 4, "capture": 2},
        "reinforce": {"objective": 9, "threat": -6, "support": 3, "capture": 2},
        "hold": {"objective": 2, "threat": -8, "support": 2, "capture": 1},
        "screen": {"objective": 6, "threat": -7, "support": 2, "capture": 2},
        "reserve_screen": {"objective": 5, "threat": -6, "support": 2, "capture": 2},
    }

    def deploy_ready_units(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
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
                plan,
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
                key=lambda coords: self._score_deployment_hex(ctx, plan, unit, coords),
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
        plan: StrategicPlan,
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
            best_hex = max(joint, key=lambda coords: self._score_deployment_hex(ctx, plan, wing, coords))
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
    def _score_deployment_hex(ctx: AIContext, plan: StrategicPlan, unit, coords: Tuple[int, int]) -> float:
        col, row = int(coords[0]), int(coords[1])
        threat = _overlay_value(ctx.overlays.get("threat"), col, row, 0.0)
        territory = ctx.overlays.get("territory")
        territory_val = territory.values.get((col, row)) if territory else None
        score = 0.0

        # Base safety
        score -= threat * 2

        # Territory comfort
        if territory_val == ctx.side:
            score += 3
        if territory_val == ctx.enemy:
            score += 5

        offensive = plan.offensive_side == ctx.side
        transport_offense = offensive and plan.transport_campaign
        deploy_hex = Hex.offset_to_axial(col, row)

        # Keep transport deployment simple: only prefer coastal/port embark-capable hexes.
        if transport_offense:
            loc = ctx.game_state.map.get_location(deploy_hex)
            is_coastal = ctx.game_state.map.is_coastal(deploy_hex)
            is_port = bool(loc and getattr(loc, "loc_type", None) == LocType.PORT.value)

            is_ground_army = (
                    getattr(unit, "is_army", lambda: False)()
                    and getattr(unit, "unit_type", None) not in (UnitType.WING, UnitType.FLEET)
            )
            is_fleet = getattr(unit, "unit_type", None) == UnitType.FLEET

            if is_ground_army:
                if is_coastal:
                    score += 12.0
                if is_port:
                    score += 18.0

            if is_fleet:
                if is_coastal:
                    score += 10.0
                if is_port:
                    score += 16.0

        # Normal offensive forward staging
        if offensive and plan.main_objective:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            dist_to_objective = deploy_hex.distance_to(main_hex)
            score += (30.0 - dist_to_objective) * 4.0
            if dist_to_objective <= 8:
                score += 25.0
            if dist_to_objective <= 4:
                score += 20.0
            if territory_val == ctx.enemy and dist_to_objective <= 10:
                score += 30.0

        # Prevent offensive overstacking in own capital once garrison is sufficient.
        loc = ctx.game_state.map.get_location(deploy_hex)
        if loc and getattr(loc, "is_capital", False) and getattr(loc, "occupier", None) == ctx.side:
            stack = ctx.game_state.map.get_units_in_hex(deploy_hex.q, deploy_hex.r)
            defenders = [
                u for u in stack
                if getattr(u, "allegiance", None) == ctx.side
                   and getattr(u, "is_on_map", False)
                   and ctx.game_state.is_combat_unit(u)
            ]
            garrison_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in defenders)
            garrison_count = len(defenders)
            min_garrison_power = max(8.0, threat * 4.0)
            min_garrison_units = 2 if threat < 2.0 else 3
            if garrison_power >= min_garrison_power and garrison_count >= min_garrison_units:
                excess = max(0, garrison_count - min_garrison_units)
                score -= 80.0 + excess * 15.0
        else:
            # Defensive / neutral location bonuses
            if loc:
                score += 3
            if loc and getattr(loc, "is_capital", False):
                score += 5

        return score

    def execute_best_movement(self, ctx: AIContext, plan: StrategicPlan, missions: List[Mission], attempt_invasion=None) -> bool:
        if self._maybe_execute_transport_action(ctx, plan):
            return True

        actions = []
        for mission in missions:
            if ctx.moved_task_groups is not None:
                if _task_group_key(mission.group) in ctx.moved_task_groups:
                    continue
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
        if ctx.moved_task_groups is not None:
            ctx.moved_task_groups.add(_task_group_key(best.group))
        return True

    def _best_move_for_mission(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        mission: Mission,
    ) -> Optional[TacticalAction]:
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

    @staticmethod
    def _fleet_has_embarked_ground(fleet) -> bool:
        passengers = list(getattr(fleet, "passengers", []) or [])
        return any(
            getattr(p, "is_army", lambda: False)()
            and getattr(p, "unit_type", None) not in (UnitType.WING, UnitType.FLEET)
            for p in passengers
        )

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

        amphibious_types = {"embark_main_effort", "transport_main_effort", "move_to_landing_area"}
        if mission.mission_type in amphibious_types and plan.main_objective:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            current_dist = mission.group.hex.distance_to(main_hex)
            next_dist = target_hex.distance_to(main_hex)
            if next_dist < current_dist:
                score += (current_dist - next_dist) * 10
            if mission.group.has_fleet:
                if ctx.game_state.map.is_coastal(target_hex):
                    score += 8
                if loc and getattr(loc, "loc_type", None) == LocType.PORT.value:
                    score += 10
            if mission.group.has_army and not mission.group.has_fleet:
                if ctx.game_state.map.is_coastal(target_hex):
                    score += 10
                stack = ctx.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
                if any(getattr(u, "allegiance", None) == ctx.side and getattr(u, "unit_type", None) == UnitType.FLEET for u in stack):
                    score += 16

        if mission.mission_type == "prepare_assault" and mission.target_hex is not None:
            front_dist = target_hex.distance_to(mission.target_hex)
            if front_dist == 1:
                score += 24
            elif front_dist == 2:
                score += 12
            elif front_dist == 0:
                score -= 20

            # Avoid isolated forward staging on contested fronts.
            adj_friendly = 0
            adj_enemy = 0
            for neighbor in target_hex.neighbors():
                nstack = ctx.game_state.map.get_units_in_hex(neighbor.q, neighbor.r)
                if any(getattr(u, "allegiance", None) == ctx.side and ctx.game_state.is_combat_unit(u) for u in nstack):
                    adj_friendly += 1
                if any(getattr(u, "allegiance", None) == ctx.enemy and ctx.game_state.is_combat_unit(u) for u in nstack):
                    adj_enemy += 1
            if front_dist <= 1 and adj_friendly < adj_enemy:
                score -= 18

        # Air support doctrine: avoid unsupported spearhead moves by air-only groups.
        if mission.group.has_wing and not mission.group.has_army and not mission.group.has_fleet:
            score += self._air_support_doctrine_score(ctx, plan, mission, target_hex)

        # Offensive mission scoring: STRICT anti-passivity
        offensive_types = {"push_objective", "main_effort_attack", "support_main_effort"}
        if mission.mission_type in offensive_types and plan.main_objective:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            current_hex = mission.group.hex
            current_dist = current_hex.distance_to(main_hex)
            next_dist = target_hex.distance_to(main_hex)
            current_col, current_row = current_hex.axial_to_offset()
            support_now = _overlay_value(friendly_power_overlay, current_col, current_row, 0.0)
            support_gain = support - support_now

            # REWARD: Advancing toward the objective
            if next_dist < current_dist:
                advance_gain = current_dist - next_dist
                # Base reward for any forward progress
                score += advance_gain * 12
                # Bonus for meaningful advances (2+ hexes)
                if advance_gain >= 2:
                    score += 20
                # High urgency bonus: reward decisive movement
                if plan.must_act or plan.urgency_score >= 0.7:
                    score += 15
            # PENALTY: Lateral or backward moves
            else:
                if support_gain <= 0:
                    # No progress AND no support gain = useless move
                    score -= 35
                else:
                    # Support gain alone doesn't justify no advance on offensive missions
                    score += min(3.0, support_gain)

            # CRITICAL: Hard penalties under pressure
            if plan.must_act:
                if next_dist >= current_dist and support_gain <= 0:
                    score -= 40  # Must act + passive = unacceptable
            if plan.urgency_score >= 0.7:
                if next_dist >= current_dist:
                    score -= 25  # High urgency + no progress = bad
            # Deadline pressure: turns running out
            if plan.objective_deadline_turn is not None:
                turns_left = plan.objective_deadline_turn - ctx.turn
                if turns_left <= 3:
                    if next_dist >= current_dist:
                        score -= 45  # Critical deadline + passive = reject
                elif turns_left <= 5:
                    if next_dist >= current_dist and support_gain <= 0:
                        score -= 25
        return score

    @staticmethod
    def _air_support_doctrine_score(ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        friendly_ground_hexes: List[Hex] = []
        for u in ctx.friendly_units:
            if not getattr(u, "is_on_map", False):
                continue
            if getattr(u, "transport_host", None) is not None:
                continue
            is_ground = getattr(u, "is_army", lambda: False)() and getattr(u, "unit_type", None) != UnitType.FLEET
            if not is_ground:
                continue
            if not getattr(u, "position", None) or u.position[0] is None:
                continue
            friendly_ground_hexes.append(Hex.offset_to_axial(*u.position))

        nearest_ground_dist = min((target_hex.distance_to(h) for h in friendly_ground_hexes), default=99)
        target_stack = ctx.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
        enemy_combat = [
            u for u in target_stack
            if getattr(u, "allegiance", None) == ctx.enemy
            and getattr(u, "is_on_map", False)
            and ctx.game_state.is_combat_unit(u)
        ]
        enemy_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in enemy_combat)
        loc = ctx.game_state.map.get_location(target_hex)
        is_enemy_location = bool(loc and getattr(loc, "occupier", None) == ctx.enemy)

        # Stay near ground effort unless attacking clearly weak/valuable targets.
        if nearest_ground_dist > 3 and enemy_power > 3:
            return -28.0
        if nearest_ground_dist > 4 and is_enemy_location and enemy_power <= 3:
            return 8.0
        if plan.main_objective and target_hex.distance_to(Hex.offset_to_axial(*plan.main_objective.coords)) <= 2:
            return 6.0
        return 0.0

    def _maybe_execute_transport_action(self, ctx: AIContext, plan: StrategicPlan) -> bool:
        """Execute transport actions in priority order: unboard, board commanders."""
        # Stage 1: Unboard passengers where appropriate.
        # Keep valid dragon commanders boarded on wings/citadels.
        for unit in ctx.friendly_units:
            passengers = list(getattr(unit, "passengers", []) or [])
            if not passengers:
                continue
            if not getattr(unit, "position", None) or unit.position[0] is None:
                continue
            carrier_hex = Hex.offset_to_axial(*unit.position)
            if unit.is_wing() or unit.is_citadel():
                ground_passengers = [
                    p for p in passengers
                    if not (hasattr(p, "is_leader") and p.is_leader())
                ]
                if self._unboard_all(ctx, unit, ground_passengers):
                    return True
            elif getattr(unit, "unit_type", None) == UnitType.FLEET and plan.transport_campaign and plan.main_objective:
                selected = self._select_fleet_unboard_passengers(ctx, plan, unit, passengers)
                if selected and self._unboard_all(ctx, unit, selected):
                    return True
            elif ctx.game_state.map.is_coastal(carrier_hex) or ctx.game_state.map.get_location(carrier_hex):
                if self._unboard_all(ctx, unit, passengers):
                    return True

        # Stage 2: Board dragon commanders onto wings lacking them (CRITICAL for HL)
        if self._board_dragon_commanders(ctx):
            return True

        # Stage 3: Same-hex fleet boarding for transport campaigns
        if plan.transport_campaign:
            board = ctx.game_state.map
            for fleet in ctx.friendly_units:
                if getattr(fleet, "unit_type", None) != UnitType.FLEET:
                    continue
                if not getattr(fleet, "position", None) or fleet.position[0] is None:
                    continue
                fleet_hex = Hex.offset_to_axial(*fleet.position)
                stack = board.unit_map.get((fleet_hex.q, fleet_hex.r)) or []
                # Collect co-located friendly passengers, prioritizing ground armies
                candidates = []
                for unit in stack:
                    if unit is fleet:
                        continue
                    if getattr(unit, "allegiance", None) != ctx.side:
                        continue
                    if getattr(unit, "transport_host", None) is not None:
                        continue
                    # First priority: ground armies
                    if getattr(unit, "is_army", lambda: False)() and getattr(unit, "unit_type", None) not in (UnitType.WING, UnitType.FLEET):
                        candidates.append((unit, 0, -float(getattr(unit, "combat_rating", 0) or 0)))
                    # Second priority: leaders (if fleet can carry)
                    elif hasattr(unit, "is_leader") and unit.is_leader():
                        if getattr(fleet, "can_carry", lambda x: True)(unit):
                            candidates.append((unit, 1, 0))
                # Sort: armies first (priority 0), then by combat rating (stronger first)
                candidates.sort(key=lambda x: (x[1], x[2]))
                for passenger, _, _ in candidates:
                    print(
                        f"[TRANSPORT] trying board {getattr(passenger, 'id', '?')} "
                        f"onto {getattr(fleet, 'id', '?')} at {fleet.position}"
                    )
                    if ctx.game_state.board_unit(fleet, passenger):
                        print(f"[TRANSPORT] Boarded {getattr(passenger, 'id', '?')} onto {getattr(fleet, 'id', '?')}")
                        return True
                    else:
                        print(
                            f"[TRANSPORT] board failed {getattr(passenger, 'id', '?')} -> {getattr(fleet, 'id', '?')}")

        return False

    @staticmethod
    def _select_fleet_unboard_passengers(ctx: AIContext, plan: StrategicPlan, fleet, passengers: List[object]) -> List[object]:
        if not plan.main_objective or not getattr(fleet, "position", None) or fleet.position[0] is None:
            return []
        fleet_hex = Hex.offset_to_axial(*fleet.position)
        if not (ctx.game_state.map.is_coastal(fleet_hex) or ctx.game_state.map.get_location(fleet_hex)):
            return []

        main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
        dist = fleet_hex.distance_to(main_hex)
        if dist > 10 and not plan.must_act and plan.urgency_score < 0.6:
            return []

        adj_friendly = 0
        adj_enemy = 0
        for neighbor in fleet_hex.neighbors():
            stack = ctx.game_state.map.get_units_in_hex(neighbor.q, neighbor.r)
            if any(getattr(u, "allegiance", None) == ctx.side and ctx.game_state.is_combat_unit(u) for u in stack):
                adj_friendly += 1
            if any(getattr(u, "allegiance", None) == ctx.enemy and ctx.game_state.is_combat_unit(u) for u in stack):
                adj_enemy += 1
        if adj_enemy > adj_friendly + 1 and dist > 3:
            return []

        selected = [
            p for p in passengers
            if getattr(p, "allegiance", None) == ctx.side
            and getattr(p, "is_on_map", False)
            and getattr(p, "is_army", lambda: False)()
            and getattr(p, "unit_type", None) not in (UnitType.WING, UnitType.FLEET)
        ]
        selected.sort(key=lambda u: (float(getattr(u, "combat_rating", 0) or 0), _unit_key(u)), reverse=True)
        return selected[:2]

    def _board_dragon_commanders(self, ctx: AIContext) -> bool:
        """Board eligible leaders onto dragon wings that lack a commander.
        
        For HL: same-flight Highlord preferred, Emperor fallback.
        For WS: equivalent valid commander logic.
        """
        wings = sorted(
            [
                u for u in ctx.friendly_units
                if getattr(u, "unit_type", None) == UnitType.WING
                and getattr(u, "race", None) == UnitRace.DRAGON
                and getattr(u, "is_on_map", False)
                and getattr(u, "transport_host", None) is None
                and getattr(u, "position", None)
                and u.position[0] is not None
            ],
            key=_unit_key,
        )
        for wing in wings:
            if self._wing_has_valid_dragon_commander(ctx, wing):
                continue
            wing_hex = Hex.offset_to_axial(*wing.position)
            stack = ctx.game_state.map.get_units_in_hex(wing_hex.q, wing_hex.r)
            leaders = [
                u for u in stack
                if getattr(u, "allegiance", None) == ctx.side
                and hasattr(u, "is_leader")
                and u.is_leader()
                and getattr(u, "is_on_map", False)
                and getattr(u, "transport_host", None) is None
            ]
            if not leaders:
                continue
            commander = self._select_dragon_commander_for_wing(ctx, wing, leaders)
            if commander and ctx.game_state.board_unit(wing, commander):
                return True
        return False

    @staticmethod
    def _wing_has_valid_dragon_commander(ctx: AIContext, wing) -> bool:
        passengers = list(getattr(wing, "passengers", []) or [])
        if not passengers:
            return False
        if getattr(wing, "allegiance", None) == HL:
            for p in passengers:
                if getattr(p, "unit_type", None) == UnitType.EMPEROR:
                    return True
                if getattr(p, "unit_type", None) != UnitType.HIGHLORD:
                    continue
                p_flight = str(getattr(getattr(p, "spec", None), "dragonflight", "") or "").strip().lower()
                wing_flight = str(getattr(getattr(wing, "spec", None), "dragonflight", "") or "").strip().lower()
                if p_flight and p_flight == wing_flight:
                    return True
            return False
        if getattr(wing, "allegiance", None) == WS:
            return any(getattr(p, "race", None) in (UnitRace.SOLAMNIC, UnitRace.ELF) for p in passengers)
        return any(hasattr(p, "is_leader") and p.is_leader() for p in passengers)

    @staticmethod
    def _select_dragon_commander_for_wing(ctx: AIContext, wing, leaders: List[object]) -> Optional[object]:
        if getattr(wing, "allegiance", None) == HL:
            return TacticalPlanner._select_hl_dragon_commander(wing, leaders)
        if getattr(wing, "allegiance", None) == WS:
            ws = [l for l in leaders if getattr(l, "race", None) in (UnitRace.SOLAMNIC, UnitRace.ELF)]
            if ws:
                return sorted(ws, key=_unit_key)[0]
        fallback = [l for l in leaders if hasattr(l, "is_leader") and l.is_leader()]
        return sorted(fallback, key=_unit_key)[0] if fallback else None

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
        failed_targets = ctx.failed_combat_targets or set()
        missions_by_group = {_task_group_key(m.group): m for m in missions}
        target_to_groups: Dict[Tuple[int, int], Dict[str, Any]] = {}

        for mission in missions:
            group = mission.group
            if not group.units:
                continue
            if all(getattr(u, "attacked_this_turn", False) for u in group.units):
                continue
            for neighbor in group.hex.neighbors():
                if (neighbor.q, neighbor.r) in failed_targets:
                    continue
                defenders = board.get_units_in_hex(neighbor.q, neighbor.r)
                defenders = [u for u in defenders if getattr(u, "allegiance", None) == ctx.enemy and getattr(u, "is_on_map", False)]
                if not defenders:
                    continue
                if not ctx.game_state.can_units_attack_stack(group.units, defenders):
                    continue
                target_key = (neighbor.q, neighbor.r)
                bucket = target_to_groups.setdefault(target_key, {"hex": neighbor, "defenders": defenders, "groups": {}})
                bucket["groups"][_task_group_key(group)] = group

        for bucket in target_to_groups.values():
            target_hex = bucket["hex"]
            defenders = bucket["defenders"]
            eligible_groups: List[TaskGroup] = sorted(
                list(bucket["groups"].values()),
                key=lambda g: (self._attack_group_strength(ctx, g), g.power),
                reverse=True,
            )
            if not eligible_groups:
                continue
            for package in self._generate_attack_packages(eligible_groups, max_groups=4):
                attackers = [
                    u for g in package for u in g.units
                    if getattr(u, "is_on_map", False)
                    and not getattr(u, "attacked_this_turn", False)
                ]
                if not attackers:
                    continue
                if not ctx.game_state.can_units_attack_stack(attackers, defenders):
                    continue
                gate = self._evaluate_combat_package_gate(ctx, plan, target_hex, attackers, defenders)
                if not gate["allow"]:
                    continue
                score = self._score_combat_package(
                    ctx,
                    plan,
                    package,
                    [missions_by_group.get(_task_group_key(g)) for g in package if missions_by_group.get(_task_group_key(g))],
                    defenders,
                    target_hex,
                    gate,
                )
                actions.append({
                    "target_hex": target_hex,
                    "attackers": attackers,
                    "groups": package,
                    "score": score,
                    "details": gate.get("note", ""),
                })

        if not actions:
            return False

        actions.sort(
            key=lambda a: (
                a["score"],
                sum(g.power for g in a["groups"]),
                len(a["groups"]),
            ),
            reverse=True,
        )
        best = actions[0]
        if best["score"] < 20:
            return False

        target_hex = best["target_hex"]
        attackers = [u for u in best["attackers"] if getattr(u, "is_on_map", False)]
        defenders_before = list(ctx.game_state.get_units_at(target_hex))
        resolution = ctx.game_state.resolve_combat(attackers, target_hex)
        show_combat_result_popup(
            ctx.game_state,
            title="AI Combat",
            attackers=attackers,
            defenders=defenders_before,
            resolution=resolution,
            context="ai_combat",
            target_hex=target_hex,
        )
        for u in attackers:
            u.attacked_this_turn = True
        if resolution and resolution.get("result") == "-/-":
            target_key = (target_hex.q, target_hex.r)
            failed_targets.add(target_key)
        if resolution and resolution.get("advance_available"):
            ctx.game_state.advance_after_combat(attackers, target_hex)
        return True

    @staticmethod
    def _generate_attack_packages(groups: List[TaskGroup], max_groups: int = 4) -> List[List[TaskGroup]]:
        pool = list(groups[:max_groups])
        if not pool:
            return []
        packages: List[List[TaskGroup]] = []
        for size in (1, 2, 3):
            if len(pool) >= size:
                packages.append(pool[:size])
        if len(pool) > 3:
            packages.append(pool)
        return packages

    @staticmethod
    def _attack_group_strength(ctx: AIContext, group: TaskGroup) -> float:
        combat_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in group.units
            if ctx.game_state.is_combat_unit(u)
        )
        if group.has_army:
            combat_power += 2.0
        if group.has_wing and not group.has_army:
            combat_power -= 1.5
        return combat_power

    def _evaluate_combat_package_gate(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        target_hex: Hex,
        attackers: List[object],
        defenders: List[object],
    ) -> Dict[str, Any]:
        att_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in attackers if ctx.game_state.is_combat_unit(u))
        def_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in defenders if ctx.game_state.is_combat_unit(u))
        if att_power <= 0 or def_power <= 0:
            return {"allow": False, "note": "no_combat_power"}

        loc = ctx.game_state.map.get_location(target_hex)
        loc_bonus = 0.0
        if loc:
            lt = str(getattr(loc, "loc_type", "") or "")
            if lt == LocType.CITY.value:
                loc_bonus += 3.0
            elif lt == LocType.PORT.value:
                loc_bonus += 2.0
            elif lt == LocType.FORTRESS.value:
                loc_bonus += 5.0
            elif lt == LocType.UNDERCITY.value:
                loc_bonus += 5.0
            if getattr(loc, "is_capital", False):
                loc_bonus += 2.0

        crossing_pen = self._crossing_attack_penalty(ctx, attackers, target_hex)
        effective_att = max(1.0, att_power - crossing_pen)
        effective_def = max(1.0, def_power + loc_bonus)
        odds = effective_att / effective_def

        offensive = plan.offensive_side == ctx.side
        min_odds = 1.05 if offensive else 1.2
        if plan.posture == "desperate_offensive":
            min_odds -= 0.08

        turns_left = None
        if plan.objective_deadline_turn is not None:
            turns_left = plan.objective_deadline_turn - ctx.turn
        critical_deadline = bool(plan.must_act or (turns_left is not None and turns_left <= 2))
        if critical_deadline:
            min_odds -= 0.2
        min_odds = max(0.85, min_odds)

        main_obj_hex = Hex.offset_to_axial(*plan.main_objective.coords) if plan.main_objective else None
        is_main_objective_hex = bool(main_obj_hex and target_hex.q == main_obj_hex.q and target_hex.r == main_obj_hex.r)

        air_combat = [u for u in attackers if ctx.game_state.is_combat_unit(u)]
        ground_present = any(getattr(u, "is_army", lambda: False)() and getattr(u, "unit_type", None) != UnitType.FLEET for u in air_combat)
        air_only = bool(air_combat) and not ground_present and any(getattr(u, "is_wing", lambda: False)() or getattr(u, "is_citadel", lambda: False)() for u in air_combat)
        if air_only and not self._is_air_special_opportunity(ctx, target_hex, defenders, is_main_objective_hex):
            return {"allow": False, "note": "air_only_gate", "odds": odds}

        if odds < 0.75 and not (critical_deadline and is_main_objective_hex and odds >= 0.6):
            return {"allow": False, "note": "suicide_odds_gate", "odds": odds}
        if crossing_pen >= 4.0 and odds < 1.35:
            return {"allow": False, "note": "crossing_gate", "odds": odds}
        if odds < min_odds:
            return {"allow": False, "note": "odds_gate", "odds": odds}

        return {
            "allow": True,
            "note": "ok",
            "odds": odds,
            "effective_att": effective_att,
            "effective_def": effective_def,
        }

    @staticmethod
    def _is_air_special_opportunity(ctx: AIContext, target_hex: Hex, defenders: List[object], is_main_objective_hex: bool) -> bool:
        def_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in defenders
            if ctx.game_state.is_combat_unit(u)
        )
        loc = ctx.game_state.map.get_location(target_hex)
        weak_enemy_location = bool(loc and getattr(loc, "occupier", None) == ctx.enemy and def_power <= 3.0)
        return weak_enemy_location or (is_main_objective_hex and def_power <= 2.0)

    @staticmethod
    def _crossing_attack_penalty(ctx: AIContext, attackers: List[object], target_hex: Hex) -> float:
        penalty = 0.0
        for u in attackers:
            if not getattr(u, "is_on_map", False):
                continue
            if not getattr(u, "position", None) or u.position[0] is None:
                continue
            if getattr(u, "unit_type", None) == UnitType.FLEET:
                continue
            if not getattr(u, "is_army", lambda: False)():
                continue
            src = Hex.offset_to_axial(*u.position)
            if target_hex not in src.neighbors():
                continue
            edge = ctx.game_state.map.get_effective_hexside(src, target_hex)
            if edge in (HexsideType.RIVER, HexsideType.RIVER.value, HexsideType.BRIDGE, HexsideType.BRIDGE.value):
                penalty += 1.0
            elif edge in (HexsideType.FORD, HexsideType.FORD.value):
                penalty += 0.7
            elif edge in (HexsideType.PASS, HexsideType.PASS.value):
                penalty += 0.5
        return penalty

    def _score_combat_package(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        groups: List[TaskGroup],
        missions: List[Mission],
        defenders: List[object],
        target_hex: Hex,
        gate: Dict[str, Any],
    ) -> float:
        total_power = sum(g.power for g in groups)
        defenders_power = sum(float(getattr(u, "combat_rating", 0) or 0) for u in defenders if ctx.game_state.is_combat_unit(u))
        odds = float(gate.get("odds", 1.0))
        score = odds * 45.0 + total_power - defenders_power * 0.4

        loc = ctx.game_state.map.get_location(target_hex)
        if loc and getattr(loc, "occupier", None) == ctx.enemy:
            score += 12.0
        if any(m and m.objective and m.objective.coords == target_hex.axial_to_offset() for m in missions):
            score += 10.0
        if plan.main_objective and target_hex.axial_to_offset() == plan.main_objective.coords:
            score += 20.0 + plan.urgency_score * 15.0
        if plan.must_act:
            score += 8.0
        if len(groups) >= 2:
            score += 6.0
        return score

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
        offensive_types = {"push_objective", "main_effort_attack", "support_main_effort"}
        if plan.offensive_side == ctx.side and mission.mission_type in offensive_types and plan.main_objective:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            dist_before = group.hex.distance_to(main_hex)
            dist_after = target_hex.distance_to(main_hex)
            if dist_after < dist_before:
                score += 8 + (dist_before - dist_after) * 2
            if dist_after == 0:
                score += 20 + plan.urgency_score * 20
            if plan.urgency_score >= 0.7:
                score += 10
            if plan.must_act:
                score += 6
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
        self._moved_task_groups_in_phase: set = set()
        # NOTE: No planning cache - board state changes after each action, so caching
        # TaskGroups/Missions across moves causes stale decisions. Rebuild fresh each time.
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
            plan,
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

    def _try_neutral_invasion(self, ctx, plan, attempt_invasion) -> bool:
        """Trigger immediate neutral invasion when a mobile ground group is already adjacent."""
        if not attempt_invasion:
            return False

        for group in self._operational.build_task_groups(ctx):
            if not group.has_army or not group.mobile_units:
                continue

            for unit in group.mobile_units:
                if not getattr(unit, "is_on_map", False):
                    continue
                if not getattr(unit, "position", None) or unit.position[0] is None:
                    continue

                unit_hex = Hex.offset_to_axial(*unit.position)
                for neighbor in unit_hex.neighbors():
                    col, row = neighbor.axial_to_offset()
                    if not ctx.game_state.is_hex_in_bounds(col, row):
                        continue

                    decision = ctx.movement_service.evaluate_neutral_entry(neighbor)
                    if not decision or not getattr(decision, "is_neutral_entry", False):
                        continue
                    if getattr(decision, "blocked_message", None):
                        continue
                    if not getattr(decision, "country_id", None):
                        continue

                    print(f"[INVASION] Triggering invasion of {decision.country_id} from {unit_hex.axial_to_offset()}")
                    attempt_invasion(decision.country_id)
                    return True

        return False

    # ---------- Movement ----------
    def execute_best_movement(self, side: str, attempt_invasion=None) -> bool:
        moved_groups = self._ensure_movement_phase_memory()
        ctx = self._build_context(side, moved_task_groups=moved_groups)
        plan = self._strategic.build_plan(ctx)
        groups = self._operational.build_task_groups(ctx)
        missions = self._operational.build_missions(ctx, plan, groups)

        # Neutral invasion override
        if self._try_neutral_invasion(ctx, plan, attempt_invasion):
            return True

        moved = self._tactical.execute_best_movement(ctx, plan, missions, attempt_invasion=attempt_invasion)
        if moved:
            self._log(f"movement: executed ({plan.posture})")
        return moved

    # ---------- Combat ----------
    def execute_best_combat(self, side: str) -> bool:
        # Clear failed combat targets at the start of each combat phase
        combat_phase_key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._combat_phase_key != combat_phase_key:
            self._combat_phase_key = combat_phase_key
            self._failed_combat_targets.clear()
        ctx = self._build_context(side)
        plan = self._strategic.build_plan(ctx)
        groups = self._operational.build_task_groups(ctx)
        missions = self._operational.build_missions(ctx, plan, groups)
        fought = self._tactical.execute_best_combat(ctx, plan, missions)
        if fought:
            self._log("combat: executed")
        return fought

    # ---------- Context ----------
    def _build_context(self, side: str, moved_task_groups: Optional[set] = None) -> AIContext:
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
            moved_task_groups=moved_task_groups,
            failed_combat_targets=self._failed_combat_targets.get(side, set()),
        )

    def _ensure_movement_phase_memory(self) -> set:
        key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._movement_phase_key != key:
            self._movement_phase_key = key
            self._moved_task_groups_in_phase = set()
        return self._moved_task_groups_in_phase

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
