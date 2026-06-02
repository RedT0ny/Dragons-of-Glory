
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple, Set

from src.content.translator import Translator
from src.content.tools import TextFormatter
from src.content import loader
from src.content.config import AI_STANCE_DATA
from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import UnitType, UnitState, LocType, UnitRace, HexsideType, GamePhase
from src.content.tools import debug_print
from src.game.map import Hex
from src.game.combat_reporting import show_combat_result_popup

translator = Translator()

def _enemy_of(side: str) -> Optional[str]:
    if side == HL: return WS
    if side == WS: return HL
    return None


def _country_alignment_for_side(country, side: str) -> float:
    alignment = getattr(country, "alignment", (0, 0)) or (0, 0)
    if side == HL:
        return float(alignment[1] if len(alignment) > 1 else 0)
    if side == WS:
        return float(alignment[0] if len(alignment) > 0 else 0)
    return 0.0


def _unit_key(unit) -> Tuple[str, int]:
    return (str(getattr(unit, "id", "")), int(getattr(unit, "ordinal", 1) or 1))


def _task_group_key(group) -> Tuple[Tuple[str, int], ...]:
    return tuple(sorted(_unit_key(u) for u in group.units))


def _overlay_value(overlay, col: int, row: int, default: float = 0.0) -> float:
    if overlay is None:
        return default
    return float(overlay.values.get((col, row), default) or default)


def _slugify(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")

_PROTECTIVE_OWN_CATEGORIES = {"control", "prevent", "survive"}
_PROTECTIVE_ENEMY_CATEGORIES = {"capture", "conquer"}


def _needs_capital_defense(side: str, hl_category: Optional[str], ws_category: Optional[str]) -> bool:
    if side == HL:
        own_cat = hl_category
        enemy_cat = ws_category
    else:
        own_cat = ws_category
        enemy_cat = hl_category
    if own_cat and own_cat.lower() in _PROTECTIVE_OWN_CATEGORIES:
        return True
    if enemy_cat and enemy_cat.lower() in _PROTECTIVE_ENEMY_CATEGORIES:
        return True
    return False


def _min_capital_ground_defenders(threat_value: float) -> int:
    return 2 if threat_value < 2.0 else 3


def _friendly_ground_combat_defenders_in_hex(ctx: "AIContext", hex_obj: Hex, side: str) -> List[object]:
    return [
        u for u in ctx.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
        if u.allegiance == side
        and u.is_on_map
        and u.is_army()
        and u.is_combat_unit()
    ]


def _can_immediately_deploy_ground_defender(ctx: "AIContext", side: str, capital_hex: Hex) -> bool:
    capital_offset = capital_hex.axial_to_offset()
    for unit in ctx.game_state.units:
        if unit.allegiance != side:
            continue
        if unit.status != UnitState.READY or unit.is_on_map:
            continue
        if not unit.is_army() or not unit.is_combat_unit():
            continue
        valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(
            unit,
            allow_territory_wide=False,
        ) or []
        if capital_offset in {tuple(v) for v in valid}:
            return True
    return False


_AI_STANCE_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def _load_ai_stance_matrix() -> Dict[str, Dict[str, str]]:
    global _AI_STANCE_CACHE
    if _AI_STANCE_CACHE is None:
        _AI_STANCE_CACHE = loader.load_ai_stance_csv(AI_STANCE_DATA)
    return _AI_STANCE_CACHE or {}


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
    enemy_victory_category: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    # Simplified invasion planning - single beachhead hex only
    beachhead_hex: Optional[Hex] = None
    beachhead_slots: List[Hex] = field(default_factory=list)
    fleet_slot_assignments: Dict[Tuple[str, int], Tuple[int, int]] = field(default_factory=dict)


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
    transport_actions_in_phase: Optional[Set[Tuple]] = None
    objective_graph: Optional[Dict[str, Any]] = None
    invasion_state: Optional[Dict[str, Any]] = None
    country_hexes_by_id: Optional[Dict[str, List[Hex]]] = None
    country_port_counts: Optional[Dict[str, int]] = None
    coastal_hexes: Optional[List[Hex]] = None
    country_id_by_offset: Optional[Dict[Tuple[int, int], str]] = None
    neutral_front_cache: Optional[Dict[str, Any]] = None
    embarked_ground: List[object] = field(default_factory=list)
    movement_logs: List[str] = field(default_factory=list)
    enemy_adjacent_combat_count: Dict[Tuple[int, int], int] = field(default_factory=dict)
    friendly_adjacent_combat_count: Dict[Tuple[int, int], int] = field(default_factory=dict)
    movement_history: Optional[Dict[Tuple[Tuple[str, int], ...], Dict[str, Any]]] = None
    front_analysis: Optional[Dict[str, Any]] = None


@dataclass
class ObjectiveGraph:
    offensive_target_countries: Set[str] = field(default_factory=set)
    defensive_target_countries: Set[str] = field(default_factory=set)
    offensive_target_locations: Set[str] = field(default_factory=set)
    defensive_target_locations: Set[str] = field(default_factory=set)
    enemy_offensive_countries: Set[str] = field(default_factory=set)
    enemy_offensive_locations: Set[str] = field(default_factory=set)
    country_importance: Dict[str, float] = field(default_factory=dict)
    location_importance: Dict[str, float] = field(default_factory=dict)
    deadline_turn: Optional[int] = None


class ObjectiveAnalyzer:
    @staticmethod
    def extract_objective_graph(game_state, side: str) -> ObjectiveGraph:
        victory = getattr(game_state.scenario_spec, "victory_conditions", {}) or {}
        enemy = _enemy_of(side)
        own_raw = victory.get(side, {})
        enemy_raw = victory.get(enemy, {}) if enemy else {}
        graph = ObjectiveGraph()
        ObjectiveAnalyzer._walk_victory_nodes(own_raw, graph, own=True)
        ObjectiveAnalyzer._walk_victory_nodes(enemy_raw, graph, own=False)
        return graph

    @staticmethod
    def _walk_victory_nodes(raw: Any, graph: ObjectiveGraph, own: bool):
        tier_weight = {"major": 3.0, "minor": 1.0}

        def walk(node: Any, tier: str):
            if isinstance(node, dict):
                if "all" in node:
                    for child in node.get("all", []) or []:
                        walk(child, tier)
                if "any" in node:
                    for child in node.get("any", []) or []:
                        walk(child, tier)
                ntype = str(node.get("type", "") or "")
                loc_id = _slugify(node.get("location", ""))
                country_id = _slugify(node.get("country", ""))
                by_turn = node.get("by_turn")
                try:
                    by_turn = int(by_turn) if by_turn is not None else None
                except Exception:
                    by_turn = None
                if by_turn is not None:
                    graph.deadline_turn = by_turn if graph.deadline_turn is None else min(graph.deadline_turn, by_turn)

                weight = tier_weight.get(tier, 1.0)
                if own:
                    if ntype == "capture_location" and loc_id:
                        graph.offensive_target_locations.add(loc_id)
                        graph.location_importance[loc_id] = graph.location_importance.get(loc_id, 0.0) + weight * 2.0
                    elif ntype == "conquer_country" and country_id:
                        graph.offensive_target_countries.add(country_id)
                        graph.country_importance[country_id] = graph.country_importance.get(country_id, 0.0) + weight * 2.0
                    elif ntype == "prevent_location_captured" and loc_id:
                        graph.defensive_target_locations.add(loc_id)
                        graph.location_importance[loc_id] = graph.location_importance.get(loc_id, 0.0) + weight * 1.5
                    elif ntype == "prevent_country_conquered" and country_id:
                        graph.defensive_target_countries.add(country_id)
                        graph.country_importance[country_id] = graph.country_importance.get(country_id, 0.0) + weight * 1.5
                else:
                    if ntype == "capture_location" and loc_id:
                        graph.enemy_offensive_locations.add(loc_id)
                    elif ntype == "conquer_country" and country_id:
                        graph.enemy_offensive_countries.add(country_id)
                return
            if isinstance(node, list):
                for child in node:
                    walk(child, tier)

        if isinstance(raw, dict):
            for tier in ("major", "minor"):
                if tier in raw:
                    walk(raw.get(tier), tier)
        elif isinstance(raw, list):
            walk(raw, "minor")

class StrategicPlanner:
    """
    Determines posture (offensive/defensive/balanced/desperate)
    Selects main objective based on victory conditions
    Decides whether to use transport (amphibious) campaigns
    Chooses beachhead locations for naval invasions
    Selects neutral expansion targets
    """
    def build_plan(self, ctx: AIContext) -> StrategicPlan:
        posture, notes, offensive_side, main_objective, deadline_turn, urgency_score, must_act, victory_category, enemy_victory_category = self._choose_posture(
            ctx)
        objectives = self._prioritize_objectives(ctx)

        # Choose a neutral expansion country first for generic control campaigns.
        invasion_target = self._choose_invasion_target(ctx, objectives)

        # IMPORTANT:
        # In campaigns like campaign 0 (control_n_countries, no authored offensive targets),
        # do NOT keep a remote generic objective like Icewall Castle.
        # Instead, anchor the main objective inside the selected expansion country.
        if (
                offensive_side == ctx.side
                and self._is_generic_control_expansion_plan(ctx, victory_category)
                and invasion_target
        ):
            country_objective = self._best_objective_in_country(objectives, invasion_target, ctx.side)
            if country_objective is not None:
                main_objective = country_objective
                notes.append(f"country_focus={invasion_target}")
                notes.append(f"main_objective_override={country_objective.id}")

        transport_campaign = self._should_use_transport(ctx, objectives, offensive_side, main_objective)

        if transport_campaign and offensive_side == ctx.side and main_objective:
            beachhead_hex, beachhead_slots = self._compute_landing_plan(ctx, main_objective, None)
        else:
            beachhead_hex = None
            beachhead_slots = []

        if beachhead_slots:
            debug_print(f"[TRANSPORT] beachhead_slots={[h.axial_to_offset() for h in beachhead_slots]}")

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
            enemy_victory_category=enemy_victory_category,
            notes=notes,
            beachhead_hex=beachhead_hex,
            beachhead_slots=beachhead_slots,
            fleet_slot_assignments=dict((ctx.invasion_state or {}).get("fleet_assignments", {})),
        )

    @staticmethod
    def _is_generic_control_expansion_plan(ctx: AIContext, victory_category: Optional[str]) -> bool:
        """True for campaigns like campaign 0: generic control victory, no explicit authored offensive targets."""
        if str(victory_category or "").lower() != "control":
            return False

        og = ctx.objective_graph or {}
        if og.get("offensive_target_countries") or og.get("offensive_target_locations"):
            return False

        return True

    @staticmethod
    def _country_frontier_metrics(ctx: AIContext, country_id: str) -> Tuple[int, int]:
        """Return:
        - number of friendly-controlled hexes adjacent to a hex in the target country
        - minimum hex distance from any friendly on-map ground unit to any hex in the target country
        """
        target_hexes: List[Hex] = list((ctx.country_hexes_by_id or {}).get(country_id, []))

        if not target_hexes:
            return 0, 999

        territory = ctx.overlays.get("territory")
        adjacent_friendly_border_hexes = 0
        seen_border: Set[Tuple[int, int]] = set()

        for th in target_hexes:
            for nb in th.neighbors():
                ncol, nrow = nb.axial_to_offset()
                if not ctx.game_state.is_hex_in_bounds(ncol, nrow):
                    continue
                if territory and territory.values.get((ncol, nrow)) == ctx.side:
                    key = (nb.q, nb.r)
                    if key not in seen_border:
                        seen_border.add(key)
                        adjacent_friendly_border_hexes += 1

        friendly_ground_hexes: List[Hex] = []
        for u in ctx.friendly_units:
            if not u.is_on_map:
                continue
            if u.transport_host is not None:
                continue
            if not u.is_army():
                continue
            if not u.position or None in u.position:
                continue
            friendly_ground_hexes.append(Hex.offset_to_axial(*u.position))

        if not friendly_ground_hexes:
            return adjacent_friendly_border_hexes, 999

        min_dist = min(
            fh.distance_to(th)
            for fh in friendly_ground_hexes
            for th in target_hexes
        )
        return adjacent_friendly_border_hexes, min_dist

    def _score_hl_expansion_country(self, ctx: AIContext, country) -> float:
        """Front-aware country score for generic control campaigns."""
        side_alignment = _country_alignment_for_side(country, ctx.side)
        if side_alignment <= -10:
            return float("-inf")

        frontier_count, min_dist = self._country_frontier_metrics(ctx, country.id)

        score = 0.0

        # Strongly prefer adjacent/frontier countries for early conquest.
        score += frontier_count * 35.0
        score += max(0.0, 14.0 - float(min_dist)) * 8.0

        # Alignment still matters a lot.
        score += side_alignment * 14.0

        # Slight preference for countries that can be attacked/expanded from current position.
        if frontier_count > 0:
            score += 40.0
            controlled_neighbors = self._friendly_controlled_neighbor_countries(ctx, country.id)
            score += min(3, len(controlled_neighbors)) * 18.0

        country_strength = float(getattr(country, "strength", 0) or 0)

        # Strength matters, but should not outweigh frontier + alignment.
        score += country_strength * 0.8

        # Strongly penalize highly WS-leaning countries that would require a large invasion effort.
        ws_alignment = float(getattr(country, "alignment", (0, 0))[0] if len(getattr(country, "alignment", (0, 0)) or ()) > 0 else 0.0)
        score -= max(0.0, ws_alignment) * 18.0

        # Prefer invasion fronts that are already materially feasible with nearby force.
        invasion_data = ctx.movement_service.get_invasion_force(country.id)
        invasion_strength = float(invasion_data.get("strength", 0) or 0)
        force_gap = country_strength - invasion_strength
        if invasion_strength <= 0:
            score -= 180.0
        elif force_gap > 0:
            score -= force_gap * 10.0
        else:
            score += min(80.0, abs(force_gap) * 4.0)

        # Ports/capitals add some value, but do not dominate.
        port_count = int((ctx.country_port_counts or {}).get(country.id, 0))
        capital_count = sum(
            1 for loc in country.locations.values()
            if getattr(loc, "is_capital", False)
        )
        score += port_count * 4.0 + capital_count * 6.0

        return score

    @staticmethod
    def _friendly_controlled_neighbor_countries(ctx: AIContext, country_id: str) -> Set[str]:
        country_hexes = list((ctx.country_hexes_by_id or {}).get(country_id, []) or [])
        if not country_hexes:
            return set()
        out: Set[str] = set()
        for h in country_hexes:
            for n in h.neighbors():
                col, row = n.axial_to_offset()
                other_id = (ctx.country_id_by_offset or {}).get((col, row))
                if not other_id or other_id == country_id:
                    continue
                other = ctx.game_state.countries.get(other_id)
                if other and getattr(other, "allegiance", None) == ctx.side:
                    out.add(str(other_id))
        return out

    @staticmethod
    def _best_objective_in_country(
            objectives: List[Objective],
            country_id: Optional[str],
            side: str,
    ) -> Optional[Objective]:
        if not country_id:
            return None

        candidates = [
            o for o in objectives
            if getattr(o, "country_id", None) == country_id
               and getattr(o, "owner", None) != side
        ]
        if not candidates:
            return None

        return max(
            candidates,
            key=lambda o: (
                o.is_capital,
                o.loc_type == LocType.PORT.value,
                o.loc_type == LocType.FORTRESS.value,
                o.value,
            ),
        )

    def _compute_landing_plan(self, ctx: AIContext, main_objective: Objective, fallback_anchor: Optional[Hex]) -> Tuple[Optional[Hex], List[Hex]]:
        state = ctx.invasion_state or {}
        needs_recompute, valid_slots, recompute_reason = self._evaluate_existing_landing_plan(ctx, main_objective, state)
        if not needs_recompute and valid_slots:
            anchor = valid_slots[0]
            debug_print(f"[TRANSPORT] reusing_landing_plan anchor={anchor.axial_to_offset()} slots={[h.axial_to_offset() for h in valid_slots]}")
            return anchor, valid_slots
        debug_print(f"[TRANSPORT] recompute_landing_plan reason={recompute_reason}")

        if not ctx.embarked_ground or not main_objective.coords:
            return None, []

        loc_hex = Hex.offset_to_axial(*main_objective.coords)
        anchor, _ = StrategicPlanner._compute_beachhead_for_location(ctx, loc_hex)

        if not anchor and fallback_anchor is not None:
            anchor = fallback_anchor

        slots = self._build_beachhead_slots(ctx, anchor, main_objective) if anchor else []
        if slots:
            new_anchor = slots[0]
            old_anchor = None
            if state.get("anchor_hex"):
                try:
                    old_anchor = Hex.offset_to_axial(int(state["anchor_hex"][0]), int(state["anchor_hex"][1]))
                except Exception:
                    old_anchor = None
            if old_anchor is not None:
                improvement = self._score_anchor_improvement(ctx, new_anchor, old_anchor, main_objective)
                if improvement <= 12.0 and any(
                    old_anchor == s for s in slots
                ):
                    new_anchor = old_anchor
            anchor = new_anchor
        return anchor, slots

    def _evaluate_existing_landing_plan(
        self,
        ctx: AIContext,
        main_objective: Objective,
        state: Dict[str, Any],
    ) -> Tuple[bool, List[Hex], str]:
        objective_id = str(getattr(main_objective, "id", "") or "")
        if str(state.get("primary_objective_id") or "") != objective_id:
            return True, [], "objective_changed"
        if not state.get("anchor_hex") or not state.get("landing_slots"):
            return True, [], "no_stored_plan"
        valid_slots = self._validate_existing_landing_slots(ctx, state, main_objective)
        if not valid_slots:
            return True, [], "slots_invalid"
        return False, valid_slots, "reuse"

    def _validate_existing_landing_slots(self, ctx: AIContext, state: Dict[str, Any], main_objective: Objective) -> List[Hex]:
        board = ctx.game_state.map
        existing: List[Hex] = []
        for item in list(state.get("landing_slots", []) or []):
            try:
                existing.append(Hex.offset_to_axial(int(item[0]), int(item[1])))
            except Exception:
                continue
        if not existing:
            return []
        if not ctx.embarked_ground:
            return []

        kept: List[Hex] = []
        for h in existing:
            col, row = h.axial_to_offset()
            if not ctx.game_state.is_hex_in_bounds(col, row):
                continue
            if not board.is_coastal(h):
                continue
            if not TacticalPlanner._can_army_exit_landing_hex(ctx, None, h):
                continue
            if not any(ctx.movement_service.can_unboard_unit_to_hex(p, h) for p in ctx.embarked_ground):
                continue
            kept.append(h)
        return kept[:4]

    def _score_anchor_improvement(self, ctx: AIContext, new_anchor: Hex, old_anchor: Hex, main_objective: Objective) -> float:
        threat = ctx.overlays.get("threat")
        new_col, new_row = new_anchor.axial_to_offset()
        old_col, old_row = old_anchor.axial_to_offset()
        target = Hex.offset_to_axial(*main_objective.coords)
        new_score = (12.0 - new_anchor.distance_to(target)) * 3.0 - _overlay_value(threat, new_col, new_row, 0.0) * 2.0
        old_score = (12.0 - old_anchor.distance_to(target)) * 3.0 - _overlay_value(threat, old_col, old_row, 0.0) * 2.0
        return new_score - old_score

    def _build_beachhead_slots(self, ctx: AIContext, beachhead_hex: Optional[Hex], main_objective: Optional[Objective]) -> List[Hex]:
        """
        Given a beachhead hex, find up to 4 coastal hexes (including the beachhead) that are good landing/unloading
        spots for currently embarked armies.
        Prioritize those that are closer to the main objective, have lower threat, and allow inland movement on the
        next turn.
        """
        if beachhead_hex is None or main_objective is None:
            return []
        board = ctx.game_state.map
        threat = ctx.overlays.get("threat")
        objective_hex = Hex.offset_to_axial(*main_objective.coords)
        objective_graph = ctx.objective_graph or {}
        target_countries = set(objective_graph.get("offensive_target_countries", set()) or set())
        if getattr(main_objective, "country_id", None):
            target_countries.add(str(main_objective.country_id))
        if not ctx.embarked_ground:
            return []

        primary_scored = []
        secondary_scored = []
        fallback_scored = []
        for h in list(ctx.coastal_hexes or []):
            col, row = h.axial_to_offset()
            dist_anchor = h.distance_to(beachhead_hex)
            if dist_anchor > 3:
                continue
            if target_countries:
                country_id = (ctx.country_id_by_offset or {}).get((col, row))
                if country_id is not None and country_id not in target_countries and h.distance_to(objective_hex) > 6:
                    continue
            if not any(ctx.movement_service.can_unboard_unit_to_hex(p, h) for p in ctx.embarked_ground):
                continue
            if not StrategicPlanner._is_land_reachable(ctx, h, objective_hex, max_depth=18):
                debug_print(f"[TRANSPORT] skip_slot=({col},{row}) not_land_reachable_to_objective")
                continue
            threat_val = _overlay_value(threat, col, row, 0.0)
            loc = board.get_location(h)
            existing_ground = sum(
                1 for u in board.get_units_in_hex(col, row)
                if u.allegiance == ctx.side
                and u.is_on_map
                and u.is_army()
            )
            score = 0.0
            score += (12.0 - h.distance_to(objective_hex)) * 3.0
            score -= threat_val * 2.0
            if loc and getattr(loc, "loc_type", None) == LocType.PORT.value:
                score += 8.0
                country_id = (ctx.country_id_by_offset or {}).get((col, row))
                if country_id in target_countries:
                    score += 10.0
            score -= existing_ground * 5.0
            if h == beachhead_hex:
                score += 6.0
            fallback_scored.append((score, h))

        primary_scored.sort(key=lambda item: item[0], reverse=True)
        secondary_scored.sort(key=lambda item: item[0], reverse=True)
        fallback_scored.sort(key=lambda item: item[0], reverse=True)
        ordered = primary_scored + secondary_scored + fallback_scored
        
        required_capacity = len(ctx.embarked_ground)
        required_slots = (required_capacity + 1) // 2  # ceil division by 2
        max_slots = max(4, required_slots)
        slots = [h for _, h in ordered[:max_slots]]
        
        total_capacity = len(slots) * 2
        if total_capacity < required_capacity:
            debug_print(f"[TRANSPORT] WARNING: insufficient landing capacity ({total_capacity}) for {required_capacity} armies")
        
        if len(slots) < 2:
            return slots
        return slots

    def _choose_posture(self, ctx: AIContext) -> Tuple[str, List[str], Optional[str], Optional[Objective], Optional[int], float, bool, Optional[str], Optional[str]]:
        notes = []
        victory_evaluator = getattr(ctx.game_state, "victory_evaluator", None)
        hl_meta = victory_evaluator.get_victory_metadata(HL) if victory_evaluator else {}
        ws_meta = victory_evaluator.get_victory_metadata(WS) if victory_evaluator else {}
        hl_category = hl_meta.get("primary_category")
        ws_category = ws_meta.get("primary_category")
        offensive_side = _determine_offensive_side(hl_category, ws_category)
        side_meta = hl_meta if ctx.side == HL else ws_meta
        victory_category = side_meta.get("primary_category")
        enemy_victory_category = ws_category if ctx.side == HL else hl_category

        friendly_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in ctx.friendly_units
            if u.is_combat_unit()
        )
        enemy_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in ctx.enemy_units
            if u.is_combat_unit()
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
        return posture, notes, offensive_side, main_objective, deadline_turn, urgency_score, must_act, victory_category, enemy_victory_category

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

        if offensive_side == ctx.side and candidates:
            enemy_authored = [obj for obj in candidates if obj.owner != ctx.side]
            if enemy_authored:
                candidates = enemy_authored

        used_generic_offensive_fallback = False
        if not candidates and offensive_side == ctx.side:
            used_generic_offensive_fallback = True
            candidates = [obj for obj in objectives if obj.owner != ctx.side]

            # Exclude strongly hostile neutral countries from generic offensive focus.
            filtered = []
            for obj in candidates:
                country = ctx.game_state.countries.get(obj.country_id) if getattr(obj, "country_id", None) else None
                if country and getattr(country, "allegiance", None) == NEUTRAL:
                    if _country_alignment_for_side(country, ctx.side) <= -10:
                        continue
                filtered.append(obj)
            candidates = filtered

        if not candidates:
            candidates = objectives

        if not candidates:
            return None, deadline_turn

        main_objective = max(
            candidates,
            key=lambda o: (o.owner != ctx.side, o.value, o.is_capital),
        )

        if main_objective.id in location_deadlines:
            deadline_turn = min(deadline_turn, location_deadlines[main_objective.id]) if deadline_turn else \
            location_deadlines[main_objective.id]
        elif main_objective.country_id in country_deadlines:
            deadline_turn = min(deadline_turn, country_deadlines[main_objective.country_id]) if deadline_turn else \
            country_deadlines[main_objective.country_id]

        return main_objective, deadline_turn

    def _compute_urgency(self, ctx: AIContext, deadline_turn: Optional[int], is_offensive_side: bool) -> float:
        if deadline_turn is not None:
            turns_left = deadline_turn - ctx.turn
            if turns_left <= 0: return 1.0
            if turns_left <= 2: return 0.9
            if turns_left <= 4: return 0.7
            if turns_left <= 6: return 0.5
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
        fleets = []
        ground_units = []

        for u in ctx.game_state.units:
            if u.allegiance == ctx.side and (u.is_on_map or u.status == UnitState.READY):
                if u.is_fleet(): fleets.append(u)
                elif u.is_army(): ground_units.append(u)

        if not fleets or not objectives or not ground_units:
            return False

        target_objectives = []
        if main_objective:
            target_objectives.append(main_objective)
        target_objectives.extend([o for o in objectives if o.owner != ctx.side and o is not main_objective][:3])
        if not target_objectives:
            return False

        starts: List[Hex] = []
        for u in ground_units:
            if u.is_on_map and u.position and None not in u.position:
                starts.append(Hex.offset_to_axial(*u.position))
                continue
            valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(u, allow_territory_wide=False) or []
            for col, row in sorted(valid)[:6]:
                starts.append(Hex.offset_to_axial(int(col), int(row)))
        if not starts:
            return False
        all_start_coastal = all(ctx.game_state.map.is_coastal(h) or ctx.game_state.map.get_location(h) for h in starts)

        for obj in target_objectives:
            target_hex = Hex.offset_to_axial(obj.coords[0], obj.coords[1])
            reachable = any(self._is_land_reachable(ctx, s, target_hex, max_depth=18) for s in starts[:10])
            if not reachable:
                return True
            if all_start_coastal and ctx.game_state.map.is_coastal(target_hex):
                min_land_dist = min(s.distance_to(target_hex) for s in starts)
                if min_land_dist >= 12:
                    return True
        return False

    @staticmethod
    def _is_land_reachable(ctx: AIContext, start_hex: Hex, target_hex: Hex, max_depth: int = 18) -> bool:
        """
        Determine if a land path exists from start_hex to target_hex within max_depth steps, considering
        only hexes that can be legally moved across by a ground unit.
        """
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

    @staticmethod
    def _dijkstra_to_coastal(
        ctx: AIContext,
        start_hex: Hex,
        coastal_hexes: List[Hex],
        max_depth: int = 24,
        ignore_enemy_armies: bool = False,
    ) -> Dict[Hex, Tuple[int, Optional[Hex]]]:
        """
        Run Dijkstra from start_hex to find the best paths to each coastal_hex.
        Returns: dict mapping coastal_hex -> (distance, next_hex_on_path)
        If ignore_enemy_armies=True, treat enemy armies as passable (for fallback).
        """
        from collections import deque

        coastal_set = {h: True for h in coastal_hexes}
        dist: Dict[Hex, int] = {start_hex: 0}
        prev: Dict[Hex, Hex] = {}
        visited: Set[Hex] = set()

        frontier = [(0, start_hex)]
        import heapq
        heapq.heapify(frontier)

        while frontier:
            current_dist, current = heapq.heappop(frontier)
            if current in visited:
                continue
            visited.add(current)

            if current in coastal_set and current != start_hex:
                continue

            if current_dist > max_depth:
                continue

            for neighbor in current.neighbors():
                if neighbor in visited:
                    continue
                col, row = neighbor.axial_to_offset()
                if not ctx.game_state.is_hex_in_bounds(col, row):
                    continue
                if not ctx.game_state.can_control_probe_project_across_hexside(current, neighbor, allegiance=ctx.side):
                    continue

                movement_cost = 1
                board = ctx.game_state.map
                if not ignore_enemy_armies and board.has_enemy_army(neighbor, ctx.side):
                    continue

                new_dist = current_dist + movement_cost
                if neighbor not in dist or new_dist < dist[neighbor]:
                    dist[neighbor] = new_dist
                    prev[neighbor] = current
                    heapq.heappush(frontier, (new_dist, neighbor))

        result: Dict[Hex, Tuple[int, Optional[Hex]]] = {}
        for coastal_hex in coastal_hexes:
            if coastal_hex in dist:
                next_hex = coastal_hex
                while next_hex in prev and prev[next_hex] != start_hex:
                    next_hex = prev[next_hex]
                result[coastal_hex] = (dist[coastal_hex], next_hex if next_hex != coastal_hex else None)
            else:
                result[coastal_hex] = (999, None)
        return result

    @staticmethod
    def _compute_beachhead_for_location(
        ctx: AIContext,
        location_hex: Hex,
    ) -> Tuple[Optional[Hex], List[Hex]]:
        """
        For a given location_hex (target location in enemy country), compute the best beachhead hexes.
        Returns (best_beachhead, candidates_by_priority) where candidates_by_priority is sorted by:
        1. closest ports not blocked by enemy armies
        2. closest coastal hexes not blocked by enemy armies
        3. ports closest to location even if blocked
        4. coastal hexes closest to location even if blocked
        """
        board = ctx.game_state.map
        all_coastal = list(ctx.coastal_hexes or [])
        port_hexes = set()

        for loc in board.locations.values():
            if getattr(loc, "loc_type", None) == LocType.PORT.value and getattr(loc, "coords", None):
                port_hex = Hex.offset_to_axial(loc.coords[0], loc.coords[1])
                if board.is_coastal(port_hex):
                    port_hexes.add(port_hex)

        coastal_only = [h for h in all_coastal if h not in port_hexes]

        dijkstra_unblocked = StrategicPlanner._dijkstra_to_coastal(
            ctx, location_hex, all_coastal, max_depth=24, ignore_enemy_armies=False
        )

        dijkstra_blocked = StrategicPlanner._dijkstra_to_coastal(
            ctx, location_hex, all_coastal, max_depth=24, ignore_enemy_armies=True
        )

        tier1_ports = []
        tier2_coastal = []
        tier3_ports_blocked = []
        tier4_coastal_blocked = []

        for port_hex in port_hexes:
            dist_unblocked, _ = dijkstra_unblocked.get(port_hex, (999, None))
            dist_blocked, path_hex = dijkstra_blocked.get(port_hex, (999, None))

            can_unload = any(
                ctx.movement_service.can_unboard_unit_to_hex(p, port_hex)
                for p in ctx.embarked_ground
            ) if ctx.embarked_ground else True

            if dist_unblocked < 999 and can_unload:
                tier1_ports.append((dist_unblocked, port_hex))
            elif dist_blocked < 999:
                tier3_ports_blocked.append((dist_blocked, port_hex))

        for coastal_hex in coastal_only:
            dist_unblocked, _ = dijkstra_unblocked.get(coastal_hex, (999, None))
            dist_blocked, path_hex = dijkstra_blocked.get(coastal_hex, (999, None))

            can_unload = any(
                ctx.movement_service.can_unboard_unit_to_hex(p, coastal_hex)
                for p in ctx.embarked_ground
            ) if ctx.embarked_ground else True

            if dist_unblocked < 999 and can_unload:
                tier2_coastal.append((dist_unblocked, coastal_hex))
            elif dist_blocked < 999:
                tier4_coastal_blocked.append((dist_blocked, coastal_hex))

        tier1_ports.sort(key=lambda x: x[0])
        tier2_coastal.sort(key=lambda x: x[0])
        tier3_ports_blocked.sort(key=lambda x: x[0])
        tier4_coastal_blocked.sort(key=lambda x: x[0])

        candidates = [h for _, h in tier1_ports] + [h for _, h in tier2_coastal] + [h for _, h in tier3_ports_blocked] + [h for _, h in tier4_coastal_blocked]
        best = candidates[0] if candidates else None

        debug_print(f"[TRANSPORT] Best landing slot: {best}\n"
                    f"[TRANSPORT] List of candidates: {candidates}")

        return best, candidates

    def _choose_invasion_target(self, ctx: AIContext, objectives: List[Objective]) -> Optional[str]:
        cache = ctx.neutral_front_cache if isinstance(ctx.neutral_front_cache, dict) else None
        if cache and cache.get("invasion_target") is not None:
            return cache.get("invasion_target")
        if ctx.side != HL:
            return None

        neutrals = [c for c in ctx.game_state.countries.values() if c.allegiance == NEUTRAL]
        if not neutrals:
            return None

        best = None
        best_score = float("-inf")

        for country in neutrals:
            score = self._score_hl_expansion_country(ctx, country)
            if score > best_score:
                best_score = score
                best = country.id
        if cache is not None:
            cache["invasion_target"] = best
            cache["staging_hexes"] = None
        return best

class OperationalPlanner:
    """
    Groups units into task groups by role (army/air/fleet)
    Assigns missions to each task group (attack, defend, transport, etc.)
    Manages capital defense assignments
    Assigns fleets to specific beachhead slots
    """
    @staticmethod
    def _fleet_has_embarked_ground_for_transport(fleet) -> bool:
        if fleet is None:
            return False
        passengers = list(getattr(fleet, "passengers", []) or [])
        return any(p.is_army() for p in passengers)

    @staticmethod
    def _group_ground_combat_count(group: TaskGroup) -> int:
        return sum(1 for u in group.units if u.is_army() and u.is_combat_unit())

    @staticmethod
    def _group_is_pinned_capital_garrison(ctx: AIContext, group: TaskGroup, threat: Any) -> bool:
        if not group.has_army or group.has_fleet:
            return False
        loc = ctx.game_state.map.get_location(group.hex)
        if not loc or not getattr(loc, "is_capital", False) or getattr(loc, "occupier", None) != ctx.side:
            return False

        local_threat = _overlay_value(threat, *group.hex.axial_to_offset(), 0.0)
        defenders = _friendly_ground_combat_defenders_in_hex(ctx, group.hex, ctx.side)
        remaining = len(defenders) - OperationalPlanner._group_ground_combat_count(group)
        min_required = _min_capital_ground_defenders(local_threat)

        if remaining < 1 and not _can_immediately_deploy_ground_defender(ctx, ctx.side, group.hex):
            return True
        return remaining < min_required

    @staticmethod
    def _neutral_border_staging_hexes(ctx: AIContext, country_id: str) -> List[Hex]:
        """Friendly-side hexes adjacent to a legal neutral-entry hex for the chosen country."""
        cache = ctx.neutral_front_cache if isinstance(ctx.neutral_front_cache, dict) else None
        if cache and cache.get("invasion_target") == country_id and isinstance(cache.get("staging_hexes"), list):
            return list(cache.get("staging_hexes") or [])

        country_hexes = list((ctx.country_hexes_by_id or {}).get(country_id, []))
        if not country_hexes:
            return []

        out: List[Hex] = []
        seen: Set[Tuple[int, int]] = set()
        country_hex_set = {(h.q, h.r) for h in country_hexes}

        # Geography-only staging: neighbors around target-country border.
        for border_hex in country_hexes:
            for h in border_hex.neighbors():
                if (h.q, h.r) in country_hex_set:
                    continue
                col, row = h.axial_to_offset()
                if not ctx.game_state.is_hex_in_bounds(col, row):
                    continue
                key = (h.q, h.r)
                if key in seen:
                    continue
                seen.add(key)
                out.append(h)

        if cache is not None and cache.get("invasion_target") == country_id:
            cache["staging_hexes"] = list(out)
        return out

    @staticmethod
    def _neutral_invasion_border_force(
            ctx: AIContext,
            groups: List[TaskGroup],
            country_id: str,
    ) -> Tuple[Set[Tuple[Tuple[str, int], ...]], int, float]:
        """Return:
        - task-group keys already adjacent to the chosen neutral target,
        - total adjacent ground-unit count,
        - total adjacent combat power.
        """
        adjacent_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        adjacent_unit_count = 0
        adjacent_power = 0.0
        target_hexes = set((h.q, h.r) for h in (ctx.country_hexes_by_id or {}).get(country_id, []))
        if not target_hexes:
            return adjacent_group_keys, adjacent_unit_count, adjacent_power

        for group in groups:
            if not group.has_army:
                continue

            ground_units = [
                u for u in group.mobile_units
                if u.is_on_map
                   and u.is_army()
                   and u.position and None not in u.position
            ]
            if not ground_units:
                continue

            group_adjacent = False
            for unit in ground_units:
                unit_hex = Hex.offset_to_axial(*unit.position)
                for neighbor in unit_hex.neighbors():
                    ncol, nrow = neighbor.axial_to_offset()
                    if not ctx.game_state.is_hex_in_bounds(ncol, nrow):
                        continue
                    if (neighbor.q, neighbor.r) not in target_hexes:
                        continue

                    group_adjacent = True
                    break
                if group_adjacent:
                    break

            if not group_adjacent:
                continue

            adjacent_group_keys.add(_task_group_key(group))
            adjacent_unit_count += len(ground_units)
            adjacent_power += sum(u.combat_rating for u in ground_units if u.is_combat_unit())

        return adjacent_group_keys, adjacent_unit_count, adjacent_power

    def build_task_groups(self, ctx: AIContext) -> List[TaskGroup]:
        board = ctx.game_state.map
        groups = []
        for (q, r), units in sorted(board.unit_map.items(), key=lambda item: (item[0][1], item[0][0])):
            stack = [u for u in units if u.allegiance == ctx.side and u.is_on_map]
            if not stack:
                continue
            hex_obj = Hex(q, r)
            debug_print(
                f"[TASK_GROUPS] stack hex={hex_obj.axial_to_offset()} "
                f"units={[TextFormatter.format_unit_log_string(u) for u in stack]}"
            )
            # Structural split by role/mobility:
            # - Ground: armies + leaders (leaders are never isolated as standalone groups)
            # - Air: wings + citadels
            # - Fleet: fleets only
            armies = [u for u in stack if u.is_army()]
            leaders = [u for u in stack if u.is_leader()]
            air_units = [u for u in stack if u.is_flier()]
            fleets = [u for u in stack if u.is_fleet()]

            role_groups: List[Tuple[List[object], bool, bool, bool]] = []
            if armies:
                army_chunks = [armies[i:i + 2] for i in range(0, len(armies), 2)]
                if leaders:
                    for idx, leader in enumerate(leaders):
                        army_chunks[idx % len(army_chunks)].append(leader)
                for army_chunk in army_chunks:
                    role_groups.append((army_chunk, True, False, False))
            if air_units:
                role_groups.append((air_units, False, True, False))
            for fleet in fleets:
                role_groups.append(([fleet], False, False, True))

            for role_units, has_army, has_air, has_fleet in role_groups:
                combat_units = [u for u in role_units if u.is_combat_unit()]
                if not combat_units:
                    continue
                power = sum(float(u.combat_rating) for u in combat_units)
                mobile_units = [
                    u for u in role_units
                    if u.transport_host is None
                    and float(u.movement_points or 0) > 0
                ]
                task_group = TaskGroup(
                    units=role_units,
                    hex=hex_obj,
                    power=power,
                    has_army=has_army,
                    has_wing=has_air,
                    has_fleet=has_fleet,
                    mobile_units=mobile_units,
                )
                groups.append(task_group)
                role = "ground" if has_army else "air" if has_air else "fleet"
                debug_print(
                    f"[TASK_GROUPS] assigned hex={hex_obj.axial_to_offset()} role={role} "
                    f"power={power:.1f} "
                    f"units={[TextFormatter.format_unit_log_string(u) for u in role_units]} "
                    f"mobile={[TextFormatter.format_unit_log_string(u) for u in mobile_units]}"
                )
        return groups

    def build_missions(self, ctx: AIContext, plan: StrategicPlan, groups: List[TaskGroup]) -> List[Mission]:
        """Assign missions to task groups based on strategic plan and current context."""
        missions = []

        def append_mission(mission: Mission):
            missions.append(mission)
            target = mission.target_hex.axial_to_offset() if mission.target_hex is not None else None
            objective_id = getattr(mission.objective, "id", None) if mission.objective is not None else None
            debug_print(
                f"[MISSIONS] group={_task_group_key(mission.group)} "
                f"hex={mission.group.hex.axial_to_offset()} "
                f"type={mission.mission_type} target={target} objective={objective_id} "
                f"priority={mission.priority:.1f}"
            )

        threat = ctx.overlays.get("threat")
        locations = self._collect_location_map(ctx)
        offensive = plan.offensive_side == ctx.side
        main_objective = plan.main_objective
        main_hex = Hex.offset_to_axial(main_objective.coords[0], main_objective.coords[1]) if main_objective else None
        invasion_stage_hexes: List[Hex] = []
        invasion_adjacent_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        invasion_force_ready = False
        primary_front_stage_hexes: List[Hex] = []

        capital_defense_groups: Dict[Hex, TaskGroup] = {}
        if _needs_capital_defense(ctx.side, plan.victory_category, plan.enemy_victory_category):
            capital_defense_groups = self._assign_capital_defenders(ctx, groups, threat)

        # Invasion staging: if we're invading a neutral country, identify groups already adjacent to the target
        # and whether we have enough committed power to justify assigning them to the invasion effort instead of
        # other missions.
        if offensive and ctx.side == HL and getattr(plan, "invasion_target", None):
            target_country = ctx.game_state.countries.get(plan.invasion_target)
            if target_country and _country_alignment_for_side(target_country, ctx.side) > -10:
                invasion_stage_hexes = self._neutral_border_staging_hexes(ctx, plan.invasion_target)
                invasion_adjacent_group_keys, invasion_adjacent_units, invasion_adjacent_power = (
                    self._neutral_invasion_border_force(ctx, groups, plan.invasion_target)
                )
                invasion_required_power = max(
                    8.0,
                    float(getattr(target_country, "strength", 0) or 0),
                )
                invasion_force_ready = (
                        invasion_adjacent_units >= 3
                        and invasion_adjacent_power >= invasion_required_power
                )

        ashore_committed = set((ctx.invasion_state or {}).get("ashore_committed_armies", set()) or set())

        main_effort_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        support_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        loaded_fleet_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        empty_fleet_group_keys: Set[Tuple[Tuple[str, int], ...]] = set()
        front_analysis = ctx.front_analysis or {}
        primary_front_country = front_analysis.get("primary_country_id")
        if offensive and primary_front_country:
            primary_front_stage_hexes = self._neutral_border_staging_hexes(ctx, str(primary_front_country))
        is_hl_control_campaign = (
            offensive
            and ctx.side == HL
            and str(plan.victory_category or "").lower() == "control"
        )
        if offensive and plan.transport_campaign and plan.beachhead_slots:
            loaded_fleet_groups: List[TaskGroup] = []
            for g in [x for x in groups if x.has_fleet]:
                fleet_unit = next((u for u in g.units if u.is_fleet()), None)
                if self._fleet_has_embarked_ground_for_transport(fleet_unit):
                    loaded_fleet_groups.append(g)
                    loaded_fleet_group_keys.add(_task_group_key(g))
                else:
                    empty_fleet_group_keys.add(_task_group_key(g))
                    debug_print(f"[TRANSPORT] skip_slot_assignment empty_fleet={getattr(fleet_unit, 'id', '?')}")
            needed_loaded_keys = {
                _unit_key(next((u for u in g.units if u.is_fleet()), None))
                for g in loaded_fleet_groups
                if next((u for u in g.units if u.is_fleet()), None) is not None
            }
            existing_assignments = dict(plan.fleet_slot_assignments or {})
            reusable_assignments = {
                fk: slot for fk, slot in existing_assignments.items() if fk in needed_loaded_keys
            }
            if len(reusable_assignments) == len(needed_loaded_keys):
                fleet_assignments = reusable_assignments
            else:
                fleet_assignments = self._assign_fleet_slots(ctx, plan, loaded_fleet_groups, ctx.transport_actions_in_phase)
            plan.fleet_slot_assignments = dict(fleet_assignments)
            if ctx.invasion_state is not None:
                ctx.invasion_state["fleet_assignments"] = dict(fleet_assignments)

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

                if plan.posture == "desperate_offensive":
                    # Desperate offensive: commit 80-85% of force
                    main_count = max(3, (len(candidates) * 80) // 100)
                    support_count = max(2, (len(candidates) * 15) // 100)
                elif is_high_urgency:
                    # High urgency: commit 70-75% of force
                    main_count = max(3, (len(candidates) * 70) // 100)
                    support_count = max(2, (len(candidates) * 15) // 100)
                elif plan.posture == "offensive":
                    # Standard offensive: commit 60-65% of force
                    main_count = max(2, (len(candidates) * 60) // 100)
                    support_count = max(1, (len(candidates) * 15) // 100)
                elif plan.posture == "cautious_offensive":
                    # Cautious offensive: commit 55-60% of force
                    main_count = max(2, (len(candidates) * 55) // 100)
                    support_count = max(1, (len(candidates) * 15) // 100)
                else:
                    # Balanced: conservative but still meaningful commitment
                    main_count = max(2, (len(candidates) * 50) // 100)
                    support_count = max(1, (len(candidates) * 15) // 100)

                # Clamp to available candidates
                if is_hl_control_campaign:
                    support_count = max(support_count, max(1, len(candidates) // 4))
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

            if (
                loc
                and getattr(loc, "is_capital", False)
                and getattr(loc, "occupier", None) == ctx.side
                and group.has_army
                and not group.has_fleet
            ):
                defenders = _friendly_ground_combat_defenders_in_hex(ctx, group.hex, ctx.side)
                group_ground = self._group_ground_combat_count(group)
                remaining_ground = len(defenders) - group_ground
                min_required = _min_capital_ground_defenders(local_threat)
                incoming_relief = any(
                    capital_hex == group.hex and _task_group_key(assigned_group) != group_key
                    for capital_hex, assigned_group in capital_defense_groups.items()
                )
                can_deploy_relief = _can_immediately_deploy_ground_defender(ctx, ctx.side, group.hex)
                if remaining_ground < 1 and not (incoming_relief or can_deploy_relief):
                    append_mission(Mission(
                        group=group,
                        mission_type="defend_allied_capital",
                        target_hex=group.hex,
                        objective=None,
                        priority=185 + local_threat * 12,
                    ))
                    continue
                if len(defenders) < min_required:
                    append_mission(Mission(
                        group=group,
                        mission_type="defend_allied_capital",
                        target_hex=group.hex,
                        objective=None,
                        priority=165 + local_threat * 10,
                    ))
                    continue

            if capital_defense_groups:
                assigned_to_capital = False
                for capital_hex, assigned_group in capital_defense_groups.items():
                    if _task_group_key(assigned_group) == group_key:
                        capital_col, capital_row = capital_hex.axial_to_offset()
                        capital_threat = _overlay_value(threat, capital_col, capital_row, 0.0)
                        append_mission(Mission(
                            group=group,
                            mission_type="defend_allied_capital",
                            target_hex=capital_hex,
                            objective=None,
                            priority=130 + capital_threat * 15,
                        ))
                        assigned_to_capital = True
                        break
                if assigned_to_capital:
                    continue

            # HL neutral-invasion staging:
            # If a neutral target has been selected but border concentration is not yet sufficient,
            # use ground armies to assemble on that specific frontier before normal objective push.
            if (
                    offensive
                    and ctx.side == HL
                    and invasion_stage_hexes
                    and not invasion_force_ready
                    and group.has_army
                    and not group.has_fleet
            ):
                if group_key in invasion_adjacent_group_keys:
                    # Already on the chosen border: hold/stay concentrated.
                    target = group.hex
                    priority = 172 + plan.urgency_score * 20 + group.power * 0.6
                else:
                    # Move toward the nearest good staging hex on the selected neutral frontier.
                    target = min(
                        invasion_stage_hexes,
                        key=lambda h: (
                            group.hex.distance_to(h),
                            h.distance_to(main_hex) if main_hex is not None else 0,
                        ),
                    )
                    dist = group.hex.distance_to(target)
                    priority = 185 + plan.urgency_score * 25 + group.power * 0.7 - dist * 2.0

                append_mission(Mission(
                    group=group,
                    mission_type="stage_neutral_invasion",
                    target_hex=target,
                    objective=None,
                    priority=priority,
                ))
                continue

            if offensive and plan.transport_campaign and main_hex:
                group_has_ashore_committed = any(_unit_key(u) in ashore_committed for u in group.units if u.is_army())
                if group.has_fleet:
                    if group_key in empty_fleet_group_keys:
                        target = group.hex
                        append_mission(Mission(
                            group=group,
                            mission_type="fleet_support",
                            target_hex=target,
                            objective=main_objective,
                            priority=66 + plan.urgency_score * 8 + group.power * 0.2,
                        ))
                        continue
                    assigned_slot = None
                    fleet_unit = next((u for u in group.units if u.is_fleet()), None)
                    assigned_offset = plan.fleet_slot_assignments.get(_unit_key(fleet_unit)) if (fleet_unit and plan.fleet_slot_assignments) else None
                    if assigned_offset:
                        assigned_slot = Hex.offset_to_axial(assigned_offset[0], assigned_offset[1])
                    target = assigned_slot if assigned_slot else (plan.beachhead_hex if plan.beachhead_hex else group.hex)
                    append_mission(Mission(
                        group=group,
                        mission_type="transport_main_effort",
                        target_hex=target,
                        objective=main_objective,
                        priority=95 + plan.urgency_score * 20 + group.power * 0.5,
                    ))
                    assigned_dbg = assigned_slot.axial_to_offset() if assigned_slot is not None else None
                    debug_print(f"[TRANSPORT] fleet_target={target.axial_to_offset()} assigned_slot={assigned_dbg}")
                    continue
                if group.has_army and (not group_has_ashore_committed) and self._group_needs_embarkation(ctx, group, main_hex):
                    embark_hex = self._best_embark_hex(ctx, group, main_hex)
                    append_mission(Mission(
                        group=group,
                        mission_type="embark_main_effort",
                        target_hex=embark_hex,
                        objective=main_objective,
                        priority=145 + plan.urgency_score * 30 + group.power * 0.8,
                    ))
                    continue
                beach_slots = list(plan.beachhead_slots or ([] if plan.beachhead_hex is None else [plan.beachhead_hex]))
                if group.has_army and not group.has_fleet and (
                    (beach_slots and any(group.hex.distance_to(s) <= 1 for s in beach_slots))
                    or group_has_ashore_committed
                ):
                    nearby_enemy = ctx.enemy_adjacent_combat_count.get((group.hex.q, group.hex.r), 0)
                    if main_objective and getattr(main_objective, "owner", None) == ctx.enemy:
                        push_objective = main_objective
                    else:
                        enemy_objectives = [o for o in plan.objectives if getattr(o, "owner", None) == ctx.enemy]
                        if enemy_objectives:
                            push_objective = min(
                                enemy_objectives,
                                key=lambda o: group.hex.distance_to(Hex.offset_to_axial(o.coords[0], o.coords[1]))
                            )
                        else:
                            push_objective = main_objective
                    if push_objective:
                        push_hex = Hex.offset_to_axial(push_objective.coords[0], push_objective.coords[1])
                        secure_mode = nearby_enemy > 0 or local_threat >= 2.0
                        mission_type = "secure_beachhead" if secure_mode else "post_landing_push"
                        priority = (142 if secure_mode else 135) + plan.urgency_score * 30 + group.power * 0.8
                        append_mission(Mission(
                            group=group,
                            mission_type=mission_type,
                            target_hex=push_hex,
                            objective=push_objective,
                            priority=priority,
                        ))
                        debug_print(f"[TRANSPORT] {mission_type} group={group_key} target={push_hex.axial_to_offset()}")
                        continue
            if (not offensive) and loc and getattr(loc, "loc_type", None) == LocType.PORT.value and loc.occupier == ctx.side:
                og = ctx.objective_graph or {}
                danger_countries = set(og.get("enemy_offensive_countries", set()) or set())
                if getattr(loc, "country_id", None) in danger_countries:
                    append_mission(Mission(
                        group=group,
                        mission_type="defend_key_location",
                        target_hex=group.hex,
                        objective=None,
                        priority=120 + local_threat * 12,
                    ))
                    continue
                
            # Priority 1: Main effort and support missions (offensive only)
            if offensive and main_hex:
                if group_key in main_effort_group_keys:
                    append_mission(Mission(
                        group=group,
                        mission_type="main_effort_attack",
                        target_hex=main_hex,
                        objective=main_objective,
                        priority=150 + plan.urgency_score * 50 + group.power,
                    ))
                    continue
                if group_key in support_group_keys:
                    append_mission(Mission(
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
                append_mission(Mission(
                    group=group,
                    mission_type=mission_type,
                    target_hex=group.hex,
                    objective=None,
                    priority=(70 if offensive else 80) + local_threat * 10,
                ))
                continue

            # Priority 3: Objective-driven missions
            objective_pool = (
                [o for o in plan.objectives if getattr(o, "owner", None) != ctx.side]
                if offensive else list(plan.objectives)
            )
            if offensive and primary_front_country:
                front_objectives = [
                    o for o in objective_pool
                    if getattr(o, "country_id", None) == primary_front_country
                ]
                if front_objectives:
                    objective_pool = front_objectives
            if not objective_pool:
                objective_pool = list(plan.objectives)
            objective, distance = self._nearest_objective(group.hex, objective_pool)
            if plan.posture == "defensive" and not offensive:
                # Defensive priority order: defend_capital > defend_key_location > reinforce > hold/screen
                
                # Check for defend_capital if own capital is threatened or undergarrisoned
                group_loc = ctx.game_state.map.get_location(group.hex)
                is_own_capital = (group_loc and getattr(group_loc, "is_capital", False) 
                                  and getattr(group_loc, "occupier", None) == ctx.side)
                if is_own_capital:
                    # Check if capital is undergarrisoned
                    stack = ctx.game_state.map.get_units_in_hex(group.hex.q, group.hex.r)
                    defenders = [
                        u for u in stack
                        if u.allegiance == ctx.side
                           and u.is_on_map
                           and u.is_combat_unit()
                    ]
                    garrison_count = len(defenders)
                    min_garrison_units = 2 if local_threat < 2.0 else 3
                    if garrison_count < min_garrison_units or local_threat >= 2.0:
                        append_mission(Mission(
                            group=group,
                            mission_type="defend_capital",
                            target_hex=group.hex,
                            objective=None,
                            priority=90 + local_threat * 10,
                        ))
                        continue
                
                # Check for defend_key_location for threatened friendly objectives
                if loc and loc.occupier == ctx.side and local_threat >= 2.0:
                    append_mission(Mission(
                        group=group,
                        mission_type="defend_key_location",
                        target_hex=group.hex,
                        objective=None,
                        priority=80 + local_threat * 10,
                    ))
                    continue
                
                # Fallback to reinforce nearest important objective/front
                if objective:
                    append_mission(Mission(
                        group=group,
                        mission_type="reinforce",
                        target_hex=Hex.offset_to_axial(objective.coords[0], objective.coords[1]),
                        objective=objective,
                        priority=max(50.0, objective.value - distance * 2),
                    ))
                    continue
                
                # Only then fallback to hold/screen
                if loc and loc.occupier == ctx.side:
                    append_mission(Mission(
                        group=group,
                        mission_type="hold",
                        target_hex=group.hex,
                        objective=None,
                        priority=40 + local_threat,
                    ))
                else:
                    append_mission(Mission(
                        group=group,
                        mission_type="screen",
                        target_hex=group.hex,
                        objective=None,
                        priority=20,
                    ))
            else:
                if objective:
                    if (
                        offensive
                        and primary_front_stage_hexes
                        and group.has_army
                        and not group.has_fleet
                        and objective.owner == ctx.side
                        and local_threat < 2.0
                    ):
                        target = min(
                            primary_front_stage_hexes,
                            key=lambda h: (
                                group.hex.distance_to(h),
                                h.distance_to(main_hex) if main_hex is not None else 0,
                            ),
                        )
                        append_mission(Mission(
                            group=group,
                            mission_type="stage_neutral_invasion",
                            target_hex=target,
                            objective=None,
                            priority=104 + plan.urgency_score * 20 + group.power * 0.45 - group.hex.distance_to(target),
                        ))
                        continue
                    if (
                        offensive
                        and main_hex is not None
                        and group.has_army
                        and not group.has_fleet
                        and group_key not in main_effort_group_keys
                        and group_key not in support_group_keys
                        and objective.owner == ctx.side
                        and local_threat < 2.0
                    ):
                        append_mission(Mission(
                            group=group,
                            mission_type="support_main_effort",
                            target_hex=main_hex,
                            objective=main_objective,
                            priority=96 + plan.urgency_score * 24 + group.power * 0.55,
                        ))
                        continue
                    if group.has_wing and not group.has_army and objective.owner == ctx.side:
                        if offensive and main_hex is not None:
                            append_mission(Mission(
                                group=group,
                                mission_type="support_main_effort",
                                target_hex=main_hex,
                                objective=main_objective,
                                priority=105 + plan.urgency_score * 25 + group.power * 0.7,
                            ))
                        else:
                            append_mission(Mission(
                                group=group,
                                mission_type="screen",
                                target_hex=group.hex,
                                objective=None,
                                priority=20 + group.power * 0.2,
                            ))
                        continue
                    mission_type = "push_objective" if objective.owner != ctx.side else "secure"
                    if (
                        offensive
                        and objective.owner != ctx.side
                        and self._should_prepare_assault(ctx, plan, group, objective)
                    ):
                        mission_type = "prepare_assault"
                    append_mission(Mission(
                        group=group,
                        mission_type=mission_type,
                        target_hex=Hex.offset_to_axial(objective.coords[0], objective.coords[1]),
                        objective=objective,
                        priority=max(20.0, objective.value - distance * 1.5)
                        + (15 if offensive and objective.owner != ctx.side else 0),
                    ))
                else:
                    append_mission(Mission(
                        group=group,
                        mission_type="reserve_screen" if offensive else "screen",
                        target_hex=group.hex,
                        objective=None,
                        priority=12 if offensive else 15,
                    ))

        missions.sort(key=lambda m: (m.priority, m.group.power), reverse=True)
        return missions

    @staticmethod
    def _assign_fleet_slots(ctx: AIContext, plan: StrategicPlan, fleet_groups: List[TaskGroup], transport_actions: Optional[Set[Tuple]] = None) -> Dict[Tuple[str, int], Tuple[int, int]]:
        """
        Assign fleets to specific beachhead slots based on:
        - Existing assignments from previous turn (if still valid and not over capacity)
        - Proximity to beachhead and main objective
        - Avoiding over-concentration in any single slot
        """
        if not fleet_groups:
            return {}
        slots = list(plan.beachhead_slots or ([] if plan.beachhead_hex is None else [plan.beachhead_hex]))
        if not slots:
            return {}
        reserved = set()
        for token in transport_actions or set():
            if isinstance(token, tuple) and len(token) >= 2 and token[0] == "landing_reserve" and isinstance(token[1], tuple):
                reserved.add(token[1])

        state = ctx.invasion_state or {}
        previous = dict(state.get("fleet_assignments", {}) or {})
        assignments: Dict[Tuple[str, int], Tuple[int, int]] = {}
        usage: Dict[Tuple[int, int], int] = defaultdict(int)
        slot_capacity: Dict[Tuple[int, int], int] = {}
        projected_load: Dict[Tuple[int, int], int] = defaultdict(int)
        for slot in slots:
            col, row = slot.axial_to_offset()
            existing_ground = sum(
                1 for u in ctx.game_state.map.get_units_in_hex(col, row)
                if u.allegiance == ctx.side
                and u.is_on_map
                and u.is_army()
            )
            cap = max(0, 2 - existing_ground)
            slot_capacity[(col, row)] = cap
            debug_print(f"[TRANSPORT_SLOT_ASSIGN] slot=({col},{row}) current_ground={existing_ground} capacity={cap} projected_load={projected_load[(col,row)]}")
        for group in sorted(fleet_groups, key=lambda g: (_task_group_key(g), -g.power)):
            fleet = next((u for u in group.units if u.is_fleet()), None)
            if fleet is None:
                continue
            fleet_key = _unit_key(fleet)
            prev_offset = previous.get(fleet_key)
            if prev_offset and any(slot.axial_to_offset() == tuple(prev_offset) for slot in slots):
                prev_key = (int(prev_offset[0]), int(prev_offset[1]))
                if projected_load[prev_key] < slot_capacity.get(prev_key, 0):
                    assignments[fleet_key] = prev_key
                    usage[prev_key] += 1
                    projected_load[prev_key] += 1
                    debug_print(f"[TRANSPORT] keep_slot fleet={fleet_key} slot={prev_key}")
                    debug_print(f"[TRANSPORT_SLOT_PICK] fleet={getattr(fleet, 'id', '?')} slot={prev_key} overflow=False")
                    continue
                if slot_capacity.get(prev_key, 0) <= 0 and all(projected_load[k] >= slot_capacity.get(k, 0) for k in slot_capacity):
                    assignments[fleet_key] = prev_key
                    usage[prev_key] += 1
                    projected_load[prev_key] += 1
                    debug_print(f"[TRANSPORT] keep_slot fleet={fleet_key} slot={prev_key}")
                    debug_print(f"[TRANSPORT_SLOT_PICK] fleet={getattr(fleet, 'id', '?')} slot={prev_key} overflow=True")
                    continue
            best_slot = None
            best_score = None
            overflow_mode = all(projected_load[k] >= slot_capacity.get(k, 0) for k in slot_capacity)
            for idx, slot in enumerate(slots):
                slot_off = slot.axial_to_offset()
                if not overflow_mode and projected_load[slot_off] >= slot_capacity.get(slot_off, 0):
                    continue
                score = usage.get(slot_off, 0) * 100 + group.hex.distance_to(slot) + idx * 8
                if slot_off in reserved:
                    score += 50
                if best_score is None or score < best_score:
                    best_score = score
                    best_slot = slot
            if best_slot is None:
                continue
            slot_off = best_slot.axial_to_offset()
            assignments[fleet_key] = slot_off
            usage[slot_off] = usage.get(slot_off, 0) + 1
            projected_load[slot_off] = projected_load.get(slot_off, 0) + 1
            debug_print(f"[TRANSPORT] assigned_slot for fleet_group={_task_group_key(group)} slot={slot_off}")
            debug_print(f"[TRANSPORT_SLOT_PICK] fleet={getattr(fleet, 'id', '?')} slot={slot_off} overflow={overflow_mode}")
            for s in slots:
                scol, srow = s.axial_to_offset()
                debug_print(f"[TRANSPORT_SLOT_ASSIGN] slot=({scol},{srow}) current_ground={max(0,2-slot_capacity[(scol,srow)])} capacity={slot_capacity[(scol,srow)]} projected_load={projected_load[(scol,srow)]}")
        return assignments

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
    def _best_embark_hex(ctx: AIContext, group: TaskGroup, main_hex: Hex) -> Hex:
        fleet_hexes = []
        for u in ctx.friendly_units:
            if not u.is_fleet():
                continue
            if not u.is_on_map:
                continue
            if not u.position or None in u.position:
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
            if u.allegiance == ctx.enemy and u.is_on_map
        ]
        defender_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in defenders
            if u.is_combat_unit()
        )
        if defender_power <= 0:
            return False

        # Offensive groups near important fronts should stage when currently underpowered,
        # unless must-act pressure requires immediate risk acceptance.
        must_force = bool(plan.must_act or (plan.objective_deadline_turn is not None and plan.objective_deadline_turn - ctx.turn <= 2))
        if must_force:
            return False
        if ctx.side == HL and str(plan.victory_category or "").lower() == "control":
            return group.power < defender_power * 0.95
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
    def _get_allied_capitals_needing_defenders(
            ctx: AIContext,
            groups: List[TaskGroup],
            threat: Any,
    ) -> List[Tuple[Hex, float]]:
        capitals_needing_defense = []
        for country in ctx.game_state.countries.values():
            if getattr(country, "allegiance", None) != ctx.side:
                continue
            for loc in country.locations.values():
                if not getattr(loc, "is_capital", False):
                    continue
                if not loc.coords:
                    continue
                capital_hex = Hex.offset_to_axial(loc.coords[0], loc.coords[1])
                col, row = loc.coords[0], loc.coords[1]
                local_threat = _overlay_value(threat, col, row, 0.0)
                defenders = _friendly_ground_combat_defenders_in_hex(ctx, capital_hex, ctx.side)
                garrison_count = len(defenders)
                min_required = _min_capital_ground_defenders(local_threat)
                if garrison_count < min_required:
                    deficit = float(min_required - garrison_count) + local_threat * 0.25
                    capitals_needing_defense.append((capital_hex, deficit))
        capitals_needing_defense.sort(key=lambda x: x[1], reverse=True)
        return capitals_needing_defense

    @staticmethod
    def _assign_capital_defenders(
            ctx: AIContext,
            groups: List[TaskGroup],
            threat: Any,
    ) -> Dict[Hex, TaskGroup]:
        """
        Assigns low-power nearby groups to defend allied capitals that are under-garrisoned or threatened.
        """
        assignments: Dict[Hex, TaskGroup] = {}
        capitals = OperationalPlanner._get_allied_capitals_needing_defenders(ctx, groups, threat)
        if not capitals:
            return assignments
        candidate_groups = [
            g for g in groups
            if g.has_army
            and not g.has_fleet
            and not OperationalPlanner._group_is_pinned_capital_garrison(ctx, g, threat)
        ]
        candidate_groups.sort(key=lambda g: g.power)
        for capital_hex, _deficit in capitals:
            if not candidate_groups:
                break
            best_group = None
            best_key = None
            for g in candidate_groups:
                key = (g.hex.distance_to(capital_hex), g.power, len(g.units))
                if best_key is None or key < best_key:
                    best_key = key
                    best_group = g
            if best_group is not None:
                assignments[capital_hex] = best_group
                candidate_groups.remove(best_group)
        return assignments

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
    """
    Deploys ready units from reserve
    Executes movement with hex-by-hex scoring
    Executes combat with odds-based filtering
    Manages transport operations (boarding/unboarding)
    Handles dragon commander boarding for HL
    """
    MOVE_WEIGHTS = {
        "push_objective": {"objective": 12, "threat": -4, "support": 2, "capture": 8},
        "post_landing_push": {"objective": 14, "threat": -4, "support": 2, "capture": 9},
        "secure_beachhead": {"objective": 10, "threat": -2, "support": 5, "capture": 8},
        "prepare_assault": {"objective": 11, "threat": -5, "support": 5, "capture": 3},
        "embark_main_effort": {"objective": 12, "threat": -5, "support": 5, "capture": 3},
        "transport_main_effort": {"objective": 14, "threat": -4, "support": 4, "capture": 7},
        "move_to_landing_area": {"objective": 12, "threat": -4, "support": 3, "capture": 6},
        "main_effort_attack": {"objective": 16, "threat": -5, "support": 4, "capture": 10},
        "support_main_effort": {"objective": 10, "threat": -4, "support": 5, "capture": 6},
        "stage_neutral_invasion": {"objective": 15, "threat": -4, "support": 4, "capture": 4},
        "secure": {"objective": 8, "threat": -5, "support": 3, "capture": 3},
        "fleet_support": {"objective": 7, "threat": -5, "support": 4, "capture": 2},
        "defend": {"objective": 4, "threat": -10, "support": 4, "capture": 2},
        "defend_key_location": {"objective": 4, "threat": -10, "support": 4, "capture": 2},
        "defend_allied_capital": {"objective": 6, "threat": -10, "support": 4, "capture": 2},
        "reinforce": {"objective": 9, "threat": -6, "support": 3, "capture": 2},
        "hold": {"objective": 2, "threat": -8, "support": 2, "capture": 1},
        "screen": {"objective": 6, "threat": -7, "support": 2, "capture": 2},
        "reserve_screen": {"objective": 5, "threat": -6, "support": 2, "capture": 2},
    }

    def __init__(self):
        self._reachable_cache_phase_key: Optional[Tuple[int, str, Any]] = None
        self._reachable_cache: Dict[Tuple[Any, ...], Any] = {}

    @staticmethod
    def _deploy_unit(
        ctx: AIContext,
        unit,
        target_hex: Hex,
        invasion_deployment_active: bool = False,
        invasion_deployment_allegiance: Optional[str] = None,
        invasion_deployment_country_id: Optional[str] = None,
    ):
        return ctx.game_state.deployment_service.deploy_unit(
            unit,
            target_hex,
            invasion_deployment_active=invasion_deployment_active,
            invasion_deployment_allegiance=invasion_deployment_allegiance,
            invasion_deployment_country_id=invasion_deployment_country_id,
        )
    
    @staticmethod
    def _can_army_exit_landing_hex(ctx: AIContext, army, landing_hex: Hex) -> bool:
        """Check if an army can legally exit landing hex to at least one adjacent inland hex."""
        board = ctx.game_state.map
        
        for neighbor in landing_hex.neighbors():
            ncol, nrow = neighbor.axial_to_offset()
            
            # a) Must be in bounds
            if not ctx.game_state.is_hex_in_bounds(ncol, nrow):
                continue
            
            # b) Must not be ocean/water-only
            if board.is_coastal(neighbor) and not board.get_location(neighbor):
                # Coastal hex without location is water-only, skip
                continue
            
            # c) Must be reachable across actual hexside according to movement/crossing rules
            if not ctx.game_state.can_control_probe_project_across_hexside(landing_hex, neighbor, allegiance=ctx.side):
                continue
            
            # d) Not blocked by mountain/impassable hexside
            # (can_control_probe_project_across_hexside already handles this)
            
            # e) Must be meaningful inland expansion (not another dead-end coastal trap)
            # Check that neighbor has at least one further inland exit
            has_further_exit = False
            for further in neighbor.neighbors():
                fcol, frow = further.axial_to_offset()
                if ctx.game_state.is_hex_in_bounds(fcol, frow):
                    if not board.is_coastal(further) or board.get_location(further):
                        has_further_exit = True
                        break
            
            if has_further_exit:
                return True
        
        return False

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
        """
        Deploy READY units from reserve, prioritizing:
        1. HL dragon wings with commanders (if HL)
        2. Transport fleets to embark hexes (if transport campaign)
        3. Transport armies to beachhead or embark hexes (if transport campaign)
        4. Other units scored by strategic value of deployment hex
        """
        deployed = 0
        ready_units = [
            u for u in ctx.game_state.units
            if u.allegiance == ctx.side
            and u.status == UnitState.READY
            and not u.is_on_map
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

        if plan.transport_campaign and plan.offensive_side == ctx.side:
            deployed += self._deploy_transport_fleets(
                ctx,
                plan,
                ready_units,
                allow_territory_wide,
                invasion_deployment_active,
                invasion_deployment_allegiance,
                invasion_deployment_country_id,
            )
            deployed += self._deploy_transport_armies(
                ctx,
                plan,
                ready_units,
                allow_territory_wide,
                invasion_deployment_active,
                invasion_deployment_allegiance,
                invasion_deployment_country_id,
            )

        if country_filter:
            deployed += self._deploy_country_capital_failsafe(
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
            valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(unit, allow_territory_wide=allow_territory_wide) or []
            if not valid:
                continue
            preferred_valid = TacticalPlanner._filter_landlocked_hexes(ctx, unit, valid)
            best_hex = max(
                preferred_valid,
                key=lambda coords: self._score_deployment_hex(ctx, plan, unit, coords),
            )
            result = self._deploy_unit(
                ctx,
                unit,
                Hex.offset_to_axial(best_hex[0], best_hex[1]),
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if result.success:
                deployed += 1
        return deployed

    def _deploy_country_capital_failsafe(
        self,
        ctx: AIContext,
        ready_units: List[object],
        allow_territory_wide: bool,
        country_filter: Optional[str],
        invasion_deployment_active: bool,
        invasion_deployment_allegiance: Optional[str],
        invasion_deployment_country_id: Optional[str],
    ) -> int:
        if not country_filter:
            return 0

        country = ctx.game_state.countries.get(country_filter)
        if not country:
            return 0

        capital_loc = next(
            (loc for loc in country.locations.values() if getattr(loc, "is_capital", False) and getattr(loc, "coords", None)),
            None,
        )
        if capital_loc is None:
            return 0

        capital_hex = Hex.offset_to_axial(capital_loc.coords[0], capital_loc.coords[1])
        stack = ctx.game_state.map.get_units_in_hex(capital_hex.q, capital_hex.r)
        if any(u.allegiance == ctx.side and u.is_on_map and u.is_combat_unit() for u in stack):
            return 0

        ready_armies = [
            u for u in ready_units
            if u.is_army()
            and u.unit_type == UnitType.INFANTRY
            and getattr(u, "land", None) == country_filter
            and not u.is_on_map
        ]
        ready_armies.sort(key=lambda u: (float(u.combat_rating), _unit_key(u)))

        valid_capital = tuple(capital_loc.coords)
        for army in ready_armies:
            valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(
                army, allow_territory_wide=allow_territory_wide
            ) or []
            if valid_capital not in {tuple(v) for v in valid}:
                continue
            result = self._deploy_unit(
                ctx,
                army,
                capital_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if result.success:
                ready_units.remove(army)
                debug_print(
                    f"[DEPLOY] capital_failsafe country={country_filter} "
                    f"unit={TextFormatter.format_unit_log_string(army)} hex={capital_hex.axial_to_offset()}"
                )
                return 1
        return 0

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
        dragons = [u for u in ready_units if (u.is_wing() and u.is_dragon())]
        highlords = [u for u in ready_units if u.unit_type in (UnitType.HIGHLORD, UnitType.EMPEROR)]

        for dragon in list(dragons):
            highlord = self._select_hl_dragon_commander(dragon, highlords)
            if not highlord:
                continue
            wing_valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(dragon, allow_territory_wide=allow_territory_wide) or []
            hl_valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(highlord, allow_territory_wide=allow_territory_wide) or []
            if not wing_valid or not hl_valid:
                continue
            hl_set = {tuple(c) for c in hl_valid}
            joint = [tuple(c) for c in wing_valid if tuple(c) in hl_set]
            if not joint:
                continue
            best_hex = max(joint, key=lambda coords: self._score_deployment_hex(ctx, plan, dragon, coords))
            target_hex = Hex.offset_to_axial(best_hex[0], best_hex[1])
            wing_res = self._deploy_unit(
                ctx,
                dragon,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if not wing_res.success:
                continue
            cmd_res = self._deploy_unit(
                ctx,
                highlord,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if cmd_res.success:
                deployed += 2
                ready_units.remove(dragon)
                ready_units.remove(highlord)
                if dragon in dragons:
                    dragons.remove(dragon)
                if highlord in highlords:
                    highlords.remove(highlord)
        return deployed

    def _deploy_transport_fleets(
            self,
            ctx,
            plan,
            ready_units,
            allow_territory_wide,
            invasion_deployment_active,
            invasion_deployment_allegiance,
            invasion_deployment_country_id,
    ) -> int:
        """Deploy READY fleets to distinct embark hexes before generic deployment."""
        if not plan.main_objective:
            return 0

        main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])

        ready_fleets = sorted(
            [u for u in ready_units if u.is_fleet() and u.status == UnitState.READY],
            key=_unit_key,
        )
        if not ready_fleets:
            return 0

        used_fleet_hexes = set()
        deployed = 0

        for fleet in ready_fleets:
            valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(
                fleet, allow_territory_wide=allow_territory_wide
            ) or []
            if not valid:
                continue

            coastal_valid = []
            for c in valid:
                h = Hex.offset_to_axial(int(c[0]), int(c[1]))
                loc = ctx.game_state.map.get_location(h)
                if ctx.game_state.map.is_coastal(h) or (
                        loc and getattr(loc, "loc_type", None) == LocType.PORT.value
                ):
                    coastal_valid.append(c)

            candidate_source = coastal_valid if coastal_valid else valid
            candidates = []

            for c in candidate_source:
                col, row = int(c[0]), int(c[1])
                h = Hex.offset_to_axial(col, row)
                score = 0.0

                loc = ctx.game_state.map.get_location(h)
                if loc and getattr(loc, "loc_type", None) == LocType.PORT.value:
                    score += 100.0
                elif ctx.game_state.map.is_coastal(h):
                    score += 50.0

                # Closer to main objective preferred
                score -= h.distance_to(main_hex) * 2.0

                # Hard penalty for hexes already chosen during this deployment pass
                if (col, row) in used_fleet_hexes:
                    score -= 1000.0

                # Also avoid hexes that already contain on-map friendly fleets
                existing_stack = ctx.game_state.map.get_units_in_hex(h.q, h.r)
                existing_friendly_fleets = sum(
                    1 for u in existing_stack
                    if u.allegiance == ctx.side
                    and u.is_fleet()
                    and u.is_on_map
                )
                if existing_friendly_fleets > 0:
                    score -= existing_friendly_fleets * 500.0

                candidates.append(((col, row), score))

            if not candidates:
                continue

            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[0][0]
            chosen_hex = Hex.offset_to_axial(chosen[0], chosen[1])

            result = self._deploy_unit(
                ctx,
                fleet,
                chosen_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if result.success:
                used_fleet_hexes.add(chosen)
                ready_units.remove(fleet)
                deployed += 1
                debug_print(f"[TRANSPORT] Deployed fleet {getattr(fleet, 'id', '?')} to {chosen_hex.axial_to_offset()}")

        return deployed

    def _deploy_transport_armies(
        self,
        ctx,
        plan,
        ready_units,
        allow_territory_wide,
        invasion_deployment_active,
        invasion_deployment_allegiance,
        invasion_deployment_country_id,
    ) -> int:
        """Deploy READY armies to fleet embark hexes for first-turn boarding."""
        if not plan.main_objective:
            return 0

        main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])

        # Collect on-map friendly fleet hexes
        fleet_hexes = []
        for u in ctx.game_state.units:
            if (u.allegiance == ctx.side and
                u.is_fleet() and
                u.is_on_map and
                u.position):
                fleet_hexes.append(Hex.offset_to_axial(*u.position))

        if not fleet_hexes:
            return 0

        # Collect READY ground armies
        ready_armies = [u for u in ready_units if (u.is_army() and u.status == UnitState.READY)]
        if not ready_armies:
            return 0

        # Sort by combat rating (stronger first)
        ready_armies.sort(key=lambda u: float(getattr(u, "combat_rating", 0) or 0), reverse=True)

        # Count armies per fleet hex for load balancing
        fleet_army_count = {h: 0 for h in fleet_hexes}

        deployed = 0
        for army in ready_armies:
            valid = ctx.game_state.deployment_service.get_valid_deployment_hexes(army, allow_territory_wide=allow_territory_wide) or []
            if not valid:
                continue
            valid = TacticalPlanner._filter_landlocked_hexes(ctx, army, valid)

            # Score candidates - SAME-HEX first, adjacent only as fallback
            same_hex_candidates = []
            adjacent_candidates = []
            for c in valid:
                col, row = int(c[0]), int(c[1])
                h = Hex.offset_to_axial(col, row)

                is_fleet_hex = h in fleet_hexes
                is_adjacent = any(h.distance_to(fh) == 1 for fh in fleet_hexes)

                if not is_fleet_hex and not is_adjacent:
                    continue

                score = 0.0
                if is_fleet_hex:
                    score += 100.0
                    score -= fleet_army_count.get(h, 0) * 10.0
                    score -= h.distance_to(main_hex)
                    same_hex_candidates.append(((col, row), score, h))
                elif is_adjacent:
                    score += 50.0
                    score -= h.distance_to(main_hex)
                    adjacent_candidates.append(((col, row), score, h))

            # Prefer same-hex; only use adjacent if no same-hex valid
            candidates = same_hex_candidates if same_hex_candidates else adjacent_candidates
            if not candidates:
                continue

            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[0][0]
            chosen_hex = Hex.offset_to_axial(chosen[0], chosen[1])

            result = self._deploy_unit(
                ctx,
                army,
                chosen_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if result.success:
                if chosen_hex in fleet_army_count:
                    fleet_army_count[chosen_hex] += 1
                ready_units.remove(army)
                deployed += 1
                debug_print(f"[TRANSPORT] Deployed army {getattr(army, 'id', '?')} to {chosen_hex.axial_to_offset()}")

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

            if unit.is_army():
                if is_coastal:
                    score += 12.0
                if is_port:
                    score += 18.0

            if unit.is_fleet():
                if is_coastal:
                    score += 6.0
                if is_port:
                    score += 10.0

                # Strong anti-clumping: do not stack all fleets in one embark hex.
                stack = ctx.game_state.map.get_units_in_hex(deploy_hex.q, deploy_hex.r)
                friendly_fleets_here = sum(
                    1 for u in stack
                    if u.allegiance == ctx.side
                    and u.is_fleet()
                    and u.is_on_map
                )
                if friendly_fleets_here > 0:
                    score -= friendly_fleets_here * 80.0

                friendly_combat_here = sum(
                    1 for u in stack
                    if u.allegiance == ctx.side
                    and u.is_on_map
                    and u.is_combat_unit()
                )
                if friendly_combat_here > 4:
                    score -= (friendly_combat_here - 4) * 8.0

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
            if unit.is_army():
                adjacent_enemy_territory = False
                adjacent_target_country = False
                target_country_id = getattr(plan.main_objective, "country_id", None)
                for neighbor in deploy_hex.neighbors():
                    ncol, nrow = neighbor.axial_to_offset()
                    if not ctx.game_state.is_hex_in_bounds(ncol, nrow):
                        continue
                    if territory and territory.values.get((ncol, nrow)) == ctx.enemy:
                        adjacent_enemy_territory = True
                    if target_country_id and (ctx.country_id_by_offset or {}).get((ncol, nrow)) == target_country_id:
                        adjacent_target_country = True
                if target_country_id and (ctx.country_id_by_offset or {}).get((col, row)) == target_country_id:
                    score += 22.0
                elif adjacent_target_country:
                    score += 14.0
                if adjacent_enemy_territory:
                    score += 12.0
                elif threat < 1.0 and dist_to_objective > 8:
                    score -= 18.0

        # Location and capital scoring
        loc = ctx.game_state.map.get_location(deploy_hex)
        is_own_capital = (loc and getattr(loc, "is_capital", False) 
                          and getattr(loc, "occupier", None) == ctx.side)
        
        # Always give location bonus if loc exists
        if loc:
            score += 3
            # Always give base capital bonus if is_capital
            if getattr(loc, "is_capital", False):
                score += 5
            if offensive and unit.is_army() and threat < 1.0 and getattr(loc, "occupier", None) == ctx.side:
                stack = ctx.game_state.map.get_units_in_hex(deploy_hex.q, deploy_hex.r)
                friendly_ground_here = sum(
                    1 for u in stack
                    if u.allegiance == ctx.side
                    and u.is_on_map
                    and u.is_army()
                )
                if friendly_ground_here >= 2:
                    score -= 90.0 + (friendly_ground_here - 1) * 35.0

        # Defensive posture: strongly reward own capital if undergarrisoned
        is_defensive = (plan.posture == "defensive" or plan.offensive_side != ctx.side)
        if is_own_capital and is_defensive:
            stack = ctx.game_state.map.get_units_in_hex(deploy_hex.q, deploy_hex.r)
            defenders = [
                u for u in stack
                if u.allegiance == ctx.side
                   and u.is_on_map
                   and u.is_combat_unit()
            ]
            garrison_power = sum(float(u.combat_rating) for u in defenders)
            garrison_count = len(defenders)
            min_garrison_power = max(8.0, threat * 4.0)
            min_garrison_units = 2 if threat < 2.0 else 3
            if garrison_power < min_garrison_power or garrison_count < min_garrison_units:
                score += 50.0  # LARGE bonus for undergarrisoned capital
            elif offensive:
                # Already sufficiently garrisoned and offensive posture - anti-overstack penalty
                excess = max(0, garrison_count - min_garrison_units)
                score -= 80.0 + excess * 15.0

        # Defensive posture: shape deployment around the defended objective and enemy approach lanes.
        if is_defensive:
            score += TacticalPlanner._defensive_objective_corridor_bonus(ctx, plan, deploy_hex)

        # Defensive: reward threatened friendly objectives, penalize low-threat rear hexes
        if is_defensive:
            # Penalize very low-threat rear hexes for ground infantry
            if unit.is_army() and threat < 0.5:
                score -= 15.0

        # Avoid deploying ground armies into terrain/hexside pockets with no legal exits.
        if TacticalPlanner._is_locked_ground_deployment_hex(ctx, unit, deploy_hex):
            score -= 1000.0
        
        return score

    @staticmethod
    def _defensive_objective_corridor_bonus(ctx: AIContext, plan: StrategicPlan, deploy_hex: Hex) -> float:
        """
        Rewards deployment on/near likely enemy approach lanes to the side's defended main objective.
        This helps avoid overfitting to local threat pockets while leaving direct objective corridors open.
        """
        main_obj = getattr(plan, "main_objective", None)
        if not main_obj or not getattr(main_obj, "coords", None):
            return 0.0
        if getattr(main_obj, "owner", None) != ctx.side:
            return 0.0

        main_hex = Hex.offset_to_axial(main_obj.coords[0], main_obj.coords[1])
        dist_to_obj = deploy_hex.distance_to(main_hex)

        # Ring bonus keeps defenders centered on objective depth, but not only in the capital hex.
        bonus = max(0.0, (14.0 - dist_to_obj) * 1.8)

        best_axis_score = 0.0
        for enemy in (ctx.enemy_units or []):
            if not enemy.is_on_map:
                continue
            if not enemy.position or None in enemy.position:
                continue
            if not enemy.is_control_unit():
                continue

            enemy_hex = Hex.offset_to_axial(enemy.position[0], enemy.position[1])
            enemy_to_obj = enemy_hex.distance_to(main_hex)
            if enemy_to_obj > 16:
                continue

            # Corridor slack: 0 means exactly on a shortest path from enemy to objective.
            slack = (enemy_hex.distance_to(deploy_hex) + dist_to_obj) - enemy_to_obj
            if slack > 2:
                continue

            pressure = max(1.0, (16.0 - enemy_to_obj) / 4.0)
            axis_score = (3.0 - float(slack)) * pressure
            if axis_score > best_axis_score:
                best_axis_score = axis_score

        bonus += best_axis_score * 3.0
        return bonus

    @staticmethod
    def _is_locked_ground_deployment_hex(ctx: AIContext, unit, deploy_hex: Hex) -> bool:
        if not unit.is_army():
            return False

        board = ctx.game_state.map
        for neighbor in deploy_hex.neighbors():
            if not board._is_valid_local_hex(neighbor):
                continue
            if board.get_movement_cost(unit, deploy_hex, neighbor) != float("inf"):
                return False
        return True

    @staticmethod
    def _filter_landlocked_hexes(ctx: AIContext, unit, valid: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """
        For armies, filter out deployment hexes that are locked in by impassable terrain or ocean on all sides.
        """
        if not valid:
            return valid
        if not unit.is_army():
            return valid

        movable = []
        for coords in valid:
            col, row = int(coords[0]), int(coords[1])
            deploy_hex = Hex.offset_to_axial(col, row)
            if not TacticalPlanner._is_locked_ground_deployment_hex(ctx, unit, deploy_hex):
                movable.append(coords)
        return movable if movable else valid

    def _ensure_reachable_cache_phase(self, ctx: AIContext):
        phase_key = (ctx.turn, ctx.side, ctx.phase)
        if self._reachable_cache_phase_key != phase_key:
            self._reachable_cache_phase_key = phase_key
            self._reachable_cache.clear()

    @staticmethod
    def _group_reachability_signature(group: TaskGroup) -> Tuple[Tuple[Any, ...], ...]:
        rows = []
        for u in sorted(group.units, key=_unit_key):
            host = u.transport_host
            host_key = _unit_key(host) if host is not None else None
            rows.append((
                _unit_key(u),
                tuple(u.position) if u.position else (None, None),
                int(float(u.movement_points or 0)),
                bool(u.moved_this_turn),
                host_key,
            ))
        return tuple(rows)

    def _get_reachable_hexes_cached(self, ctx: AIContext, group: TaskGroup):
        self._ensure_reachable_cache_phase(ctx)
        cache_key = (
            _task_group_key(group),
            group.hex.q,
            group.hex.r,
            self._group_reachability_signature(group),
        )
        cached = self._reachable_cache.get(cache_key)
        if cached is not None:
            return cached, True
        computed = ctx.movement_service.get_reachable_hexes(group.units)
        self._reachable_cache[cache_key] = computed
        return computed, False

    @staticmethod
    def _is_follow_up_worthy(plan: StrategicPlan, action: TacticalAction) -> bool:
        if action.target_hex is None:
            return False
        if action.target_hex == action.group.hex:
            return False
        offensive_types = {
            "push_objective",
            "main_effort_attack",
            "support_main_effort",
            "prepare_assault",
            "post_landing_push",
            "secure_beachhead",
            "stage_neutral_invasion",
            "embark_main_effort",
            "transport_main_effort",
        }
        if action.details not in offensive_types:
            return False
        if action.score >= 5:
            return True
        if getattr(plan, "must_act", False) and action.score >= 0:
            return True
        return False

    @staticmethod
    def _movement_history_penalty(
        ctx: AIContext,
        plan: StrategicPlan,
        mission: Mission,
        target_hex: Hex,
    ) -> float:
        history = ctx.movement_history or {}
        entry = history.get(_task_group_key(mission.group))
        if not entry:
            return 0.0
        if ctx.turn - int(entry.get("turn", ctx.turn) or ctx.turn) > 2:
            return 0.0

        current = mission.group.hex.axial_to_offset()
        target = target_hex.axial_to_offset()
        if target == current:
            return 0.0

        last_from = entry.get("from")
        last_to = entry.get("to")
        last_mission = entry.get("mission")
        mission_changed = last_mission is not None and last_mission != mission.mission_type

        current_threat = _overlay_value(ctx.overlays.get("threat"), current[0], current[1], 0.0)
        target_threat = _overlay_value(ctx.overlays.get("threat"), target[0], target[1], 0.0)
        threat_relief = max(0.0, current_threat - target_threat)

        objective_gain = 0
        if mission.target_hex is not None:
            objective_gain = mission.group.hex.distance_to(mission.target_hex) - target_hex.distance_to(mission.target_hex)
        main_gain = 0
        if plan.main_objective is not None:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            main_gain = mission.group.hex.distance_to(main_hex) - target_hex.distance_to(main_hex)

        justified = (
            mission_changed
            or threat_relief >= 1.5
            or objective_gain > 0
            or main_gain > 0
            or (plan.must_act and max(objective_gain, main_gain) >= 0)
        )

        penalty = 0.0
        if last_from == target and last_to == current and not justified:
            penalty -= 55.0
        elif last_from == target and last_to == current:
            penalty -= 18.0

        repeat_count = int(entry.get("repeat_count", 0) or 0)
        if repeat_count >= 2 and {last_from, last_to} == {current, target} and not justified:
            penalty -= 20.0 * min(3, repeat_count - 1)

        return penalty

    @staticmethod
    def _record_movement_history(
        ctx: AIContext,
        mission: Optional[Mission],
        action: TacticalAction,
        from_offset: Tuple[int, int],
        to_offset: Tuple[int, int],
    ):
        if ctx.movement_history is None or mission is None or from_offset == to_offset:
            return
        group_key = _task_group_key(action.group)
        previous = ctx.movement_history.get(group_key, {})
        repeat_count = 1
        if previous.get("from") == to_offset and previous.get("to") == from_offset:
            repeat_count = int(previous.get("repeat_count", 1) or 1) + 1
        ctx.movement_history[group_key] = {
            "from": from_offset,
            "to": to_offset,
            "mission": mission.mission_type,
            "turn": ctx.turn,
            "repeat_count": repeat_count,
        }

    @staticmethod
    def _front_direction_score(ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        if plan.offensive_side != ctx.side:
            return 0.0
        if mission.group.has_fleet:
            return 0.0
        if not (mission.group.has_army or mission.group.has_wing):
            return 0.0
        if mission.mission_type in {
            "defend",
            "defend_capital",
            "defend_allied_capital",
            "defend_key_location",
            "hold",
            "secure_beachhead",
            "transport_main_effort",
            "embark_main_effort",
            "move_to_landing_area",
        }:
            return 0.0

        front = ctx.front_analysis or {}
        country_id = front.get("primary_country_id")
        if not country_id:
            return 0.0
        active_country = getattr(mission.objective, "country_id", None) if mission.objective is not None else None
        if active_country is None and mission.mission_type in {"main_effort_attack", "support_main_effort"}:
            active_country = getattr(plan.main_objective, "country_id", None) if plan.main_objective else None
        if active_country is not None and str(active_country) != str(country_id):
            return 0.0
        country_hexes = list((ctx.country_hexes_by_id or {}).get(str(country_id), []) or [])
        if not country_hexes:
            return 0.0

        current_hex = mission.group.hex
        current_dist = min(current_hex.distance_to(h) for h in country_hexes)
        next_dist = min(target_hex.distance_to(h) for h in country_hexes)
        progress = current_dist - next_dist
        if progress > 0:
            return min(18.0, progress * 8.0)
        if progress < 0:
            penalty = min(20.0, abs(progress) * 7.0)
            if mission.mission_type in {"main_effort_attack", "support_main_effort", "push_objective", "stage_neutral_invasion"}:
                penalty += 6.0
            return -penalty
        return 0.0

    @staticmethod
    def _army_stack_limit_for_hex(ctx: AIContext, hex_obj: Hex) -> int:
        loc = ctx.game_state.map.get_location(hex_obj)
        if loc and (
            getattr(loc, "is_capital", False)
            or getattr(loc, "loc_type", None) in {LocType.CITY.value, LocType.PORT.value, LocType.FORTRESS.value}
        ):
            return 3
        return 2

    @staticmethod
    def _front_progress_gain(ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        current_hex = mission.group.hex
        gains: List[float] = []
        if mission.target_hex is not None:
            gains.append(float(current_hex.distance_to(mission.target_hex) - target_hex.distance_to(mission.target_hex)))
        if plan.main_objective is not None:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            gains.append(float(current_hex.distance_to(main_hex) - target_hex.distance_to(main_hex)))

        front = ctx.front_analysis or {}
        country_id = front.get("primary_country_id")
        country_hexes = list((ctx.country_hexes_by_id or {}).get(str(country_id), []) or []) if country_id else []
        if country_hexes:
            current_dist = min(current_hex.distance_to(h) for h in country_hexes)
            target_dist = min(target_hex.distance_to(h) for h in country_hexes)
            gains.append(float(current_dist - target_dist))
        return max(gains, default=0.0)

    @staticmethod
    def _front_congestion_score(ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        if plan.offensive_side != ctx.side:
            return 0.0
        if mission.group.has_fleet or not mission.group.has_army:
            return 0.0
        if target_hex == mission.group.hex:
            return 0.0
        if mission.mission_type not in {
            "main_effort_attack",
            "support_main_effort",
            "push_objective",
            "stage_neutral_invasion",
            "post_landing_push",
            "prepare_assault",
        }:
            return 0.0

        moving_ids = {id(u) for u in mission.group.units}
        moving_armies = sum(1 for u in mission.group.units if u.is_army())
        if moving_armies <= 0:
            return 0.0

        def friendly_armies_at(hex_obj: Hex, exclude_moving: bool) -> int:
            return sum(
                1
                for u in ctx.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
                if u.allegiance == ctx.side
                and u.is_on_map
                and u.is_army()
                and (not exclude_moving or id(u) not in moving_ids)
            )

        current_hex = mission.group.hex
        progress_gain = TacticalPlanner._front_progress_gain(ctx, plan, mission, target_hex)
        target_existing = friendly_armies_at(target_hex, exclude_moving=True)
        target_limit = TacticalPlanner._army_stack_limit_for_hex(ctx, target_hex)
        projected_target = target_existing + moving_armies
        target_is_objective = bool(mission.target_hex is not None and target_hex == mission.target_hex)

        score = 0.0
        if projected_target > target_limit:
            score -= 140.0 + (projected_target - target_limit) * 40.0
        elif target_existing >= target_limit:
            score -= 70.0
        elif target_existing > 0 and projected_target >= target_limit and not target_is_objective:
            score -= 22.0
        elif target_existing > 0 and projected_target == target_limit - 1 and progress_gain <= 0:
            score -= 10.0

        current_armies = friendly_armies_at(current_hex, exclude_moving=False)
        current_limit = TacticalPlanner._army_stack_limit_for_hex(ctx, current_hex)
        if current_armies >= current_limit and progress_gain > 0:
            score += 14.0 + min(16.0, max(0, current_armies - current_limit + 1) * 6.0)
        elif current_armies > current_limit and progress_gain >= 0:
            score += 8.0

        current_loc = ctx.game_state.map.get_location(current_hex)
        if current_loc and getattr(current_loc, "occupier", None) == ctx.side and progress_gain > 0:
            current_col, current_row = current_hex.axial_to_offset()
            current_threat = _overlay_value(ctx.overlays.get("threat"), current_col, current_row, 0.0)
            if current_threat < 1.0 and current_armies >= 2:
                score += 10.0
        return score

    def _should_lock_group_after_action(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        mission: Mission,
        action: TacticalAction,
    ) -> bool:
        if action.target_hex is None or action.target_hex == mission.group.hex:
            return True
        if not any(float(getattr(u, "movement_points", 0) or 0) > 0 for u in mission.group.mobile_units):
            return True
        return not self._is_follow_up_worthy(plan, action)

    def execute_best_movement(self, ctx: AIContext, plan: StrategicPlan, missions: List[Mission], attempt_invasion=None) -> bool:
        transport_t0 = perf_counter()
        transport_executed, commander_boarded = self._maybe_execute_transport_action(ctx, plan, allow_commander_boarding=True)
        transport_ms = (perf_counter() - transport_t0) * 1000.0
        if transport_executed:
            ctx.movement_logs.append(f"movement_tactical_exec transport_action={transport_ms:.1f}ms moved=True")
            return True

        eval_start = perf_counter()
        eval_reach_ms = 0.0
        eval_score_ms = 0.0
        eval_candidates = 0
        eval_missions = 0
        cache_hits = 0
        cache_misses = 0
        actions = []
        for mission in missions:
            if ctx.moved_task_groups is not None:
                if _task_group_key(mission.group) in ctx.moved_task_groups:
                    continue
            if not mission.group.mobile_units:
                continue
            action, perf = self._best_move_for_mission(ctx, plan, mission)
            eval_missions += 1
            eval_reach_ms += float(perf.get("reach_ms", 0.0))
            eval_score_ms += float(perf.get("score_ms", 0.0))
            eval_candidates += int(perf.get("candidates", 0))
            if perf.get("cache_hit"):
                cache_hits += 1
            else:
                cache_misses += 1
            if action:
                actions.append(action)
        eval_total_ms = (perf_counter() - eval_start) * 1000.0
        ctx.movement_logs.append(
            "movement_tactical "
            f"eval_total={eval_total_ms:.1f}ms "
            f"missions_eval={eval_missions} candidates={eval_candidates} "
            f"reach={eval_reach_ms:.1f}ms score={eval_score_ms:.1f}ms "
            f"cache_hits={cache_hits} cache_misses={cache_misses}"
        )
        if not actions:
            if commander_boarded:
                ctx.movement_logs.append(f"movement_tactical_exec transport_action={transport_ms:.1f}ms moved=True")
                return True
            return False

        actions.sort(key=lambda a: (a.score, a.group.power), reverse=True)
        best = actions[0]
        if best.score < 5 and not self._is_follow_up_worthy(plan, best):
            if commander_boarded:
                ctx.movement_logs.append(f"movement_tactical_exec transport_action={transport_ms:.1f}ms moved=True")
                return True
            return False

        target_hex = best.target_hex
        if target_hex is None:
            return False
        if target_hex.q == best.group.hex.q and target_hex.r == best.group.hex.r:
            ctx.movement_logs.append(
                "movement_tactical_exec "
                f"transport_action={transport_ms:.1f}ms "
                "move_units=0.0ms "
                f"units_in_group={len(best.group.units)} moved_units={len(best.group.units)} errors=0 no_op=True"
            )
            for unit in best.group.units:
                pos = tuple(unit.position) if unit.position else (None, None)
                unit_name = TextFormatter.format_unit_log_string(unit)
                ctx.movement_logs.append(f"movement unit={unit_name} from={pos} to={pos}")
            mission = next((m for m in missions if _task_group_key(m.group) == _task_group_key(best.group)), None)
            if ctx.moved_task_groups is not None and (mission is None or self._should_lock_group_after_action(ctx, plan, mission, best)):
                ctx.moved_task_groups.add(_task_group_key(best.group))
            return True

        decision = ctx.movement_service.invasion_handler.evaluate_neutral_entry(target_hex)
        if decision.is_neutral_entry:
            if decision.blocked_message:
                return False
            if decision.confirmation_prompt and attempt_invasion:
                attempt_invasion(decision.country_id or "unknown")
                return True

        before_positions = {u: tuple(u.position) if u.position else (None, None) for u in best.group.units}
        execute_t0 = perf_counter()
        move_result = ctx.movement_service.move_units_to_hex(best.group.units, target_hex)
        execute_ms = (perf_counter() - execute_t0) * 1000.0
        ctx.movement_logs.append(
            "movement_tactical_exec "
            f"transport_action={transport_ms:.1f}ms "
            f"move_units={execute_ms:.1f}ms "
            f"units_in_group={len(best.group.units)} moved_units={len(move_result.moved)} "
            f"errors={len(move_result.errors)}"
        )
        if move_result.errors:
            return False
        for unit in move_result.moved:
            prev = before_positions.get(unit, (None, None))
            now = tuple(unit.position) if unit.position else (None, None)
            unit_name = TextFormatter.format_unit_log_string(unit)
            ctx.movement_logs.append(f"movement unit={unit_name} from={prev} to={now}")
        mission = next((m for m in missions if _task_group_key(m.group) == _task_group_key(best.group)), None)
        self._record_movement_history(
            ctx,
            mission,
            best,
            best.group.hex.axial_to_offset(),
            target_hex.axial_to_offset(),
        )
        if ctx.moved_task_groups is not None and (mission is None or self._should_lock_group_after_action(ctx, plan, mission, best)):
            ctx.moved_task_groups.add(_task_group_key(best.group))
        return True

    def _best_move_for_mission(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        mission: Mission,
    ) -> Tuple[Optional[TacticalAction], Dict[str, Any]]:
        group = mission.group
        t0 = perf_counter()
        move_range, cache_hit = self._get_reachable_hexes_cached(ctx, group)
        t1 = perf_counter()
        candidates = list(move_range.reachable_coords)
        if not candidates:
            return None, {
                "reach_ms": (t1 - t0) * 1000.0,
                "score_ms": 0.0,
                "candidates": 0,
                "cache_hit": cache_hit,
            }
        current = group.hex.axial_to_offset()
        if current not in candidates:
            candidates.append(current)
        target_offset = mission.target_hex.axial_to_offset() if mission.target_hex is not None else None
        assigned_reachable = bool(target_offset and target_offset in candidates)
        assigned_preserved = True

        if len(candidates) > 80:
            candidates = self._prefilter_move_candidates(ctx, plan, mission, candidates, current, target_offset, limit=80)
            truncated = list(candidates[:80])
            if target_offset and assigned_reachable and target_offset not in truncated:
                truncated[-1] = target_offset
                assigned_preserved = True
            elif target_offset and assigned_reachable:
                assigned_preserved = True
            elif target_offset:
                assigned_preserved = False
            candidates = truncated
        elif target_offset and assigned_reachable:
            assigned_preserved = target_offset in candidates

        if mission.mission_type == "transport_main_effort" and mission.group.has_fleet:
            fleet = next((u for u in group.units if u.is_fleet()), None)
            fleet_id = getattr(fleet, "id", "?")
            pos = current
            assigned_dbg = target_offset if target_offset is not None else None
            debug_print(
                f"[TRANSPORT_MOVE] fleet={fleet_id} pos={pos} assigned={assigned_dbg} "
                f"reachable_count={len(move_range.reachable_coords)} assigned_reachable={assigned_reachable} "
                f"assigned_preserved={assigned_preserved}"
            )

        score_start = perf_counter()
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
        if best_action and mission.mission_type == "transport_main_effort" and mission.group.has_fleet and mission.target_hex is not None:
            fleet = next((u for u in group.units if u.is_fleet()), None)
            fleet_id = getattr(fleet, "id", "?")
            chosen = best_action.target_hex.axial_to_offset()
            assigned = mission.target_hex.axial_to_offset()
            dist_before = group.hex.distance_to(mission.target_hex)
            dist_after = best_action.target_hex.distance_to(mission.target_hex)
            on_slot = bool(best_action.target_hex == mission.target_hex)
            debug_print(
                f"[TRANSPORT_MOVE_RESULT] fleet={fleet_id} chosen={chosen} assigned={assigned} "
                f"dist_before={dist_before} dist_after={dist_after} on_slot={on_slot}"
            )
        score_end = perf_counter()
        return best_action, {
            "reach_ms": (t1 - t0) * 1000.0,
            "score_ms": (score_end - score_start) * 1000.0,
            "candidates": len(candidates),
            "cache_hit": cache_hit,
        }

    def _prefilter_move_candidates(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        mission: Mission,
        candidates: List[Tuple[int, int]],
        current: Tuple[int, int],
        target_offset: Optional[Tuple[int, int]],
        limit: int = 80,
    ) -> List[Tuple[int, int]]:
        if len(candidates) <= limit:
            return candidates
        if mission.target_hex is None:
            return candidates

        current_hex = mission.group.hex
        objective_hex = mission.target_hex
        main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1]) if plan.main_objective else None
        offensive_types = {"push_objective", "main_effort_attack", "support_main_effort"}
        threat_overlay = ctx.overlays.get("threat")

        def rank(candidate: Tuple[int, int]) -> Tuple[float, float, float]:
            hex_obj = Hex.offset_to_axial(candidate[0], candidate[1])
            target_progress = current_hex.distance_to(objective_hex) - hex_obj.distance_to(objective_hex)
            main_progress = 0.0
            if mission.mission_type in offensive_types and main_hex is not None:
                main_progress = current_hex.distance_to(main_hex) - hex_obj.distance_to(main_hex)
            threat = _overlay_value(threat_overlay, candidate[0], candidate[1], 0.0)
            return (main_progress, target_progress, -threat)

        prioritized = sorted(candidates, key=rank, reverse=True)
        preserved: List[Tuple[int, int]] = []
        for item in (current, target_offset):
            if item and item in prioritized and item not in preserved:
                preserved.append(item)
        selected = list(prioritized[:limit])
        for item in preserved:
            if item not in selected:
                selected[-1] = item
        return selected

    @staticmethod
    def _fleet_has_embarked_ground(fleet) -> bool:
        passengers = list(getattr(fleet, "passengers", []) or [])
        return any(p.is_army() for p in passengers)

    def _score_move(self, ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        weights = self.MOVE_WEIGHTS.get(mission.mission_type, self.MOVE_WEIGHTS["screen"])
        col, row = target_hex.axial_to_offset()
        threat = _overlay_value(ctx.overlays.get("threat"), col, row, 0.0)
        friendly_power_overlay = ctx.overlays.get("ws_power") if ctx.side == WS else ctx.overlays.get("hl_power")
        support = _overlay_value(friendly_power_overlay, col, row, 0.0)
        territory = ctx.overlays.get("territory")
        territory_val = territory.values.get((col, row)) if territory else None
        current_hex = mission.group.hex
        current_col, current_row = current_hex.axial_to_offset()
        current_threat = _overlay_value(ctx.overlays.get("threat"), current_col, current_row, 0.0)

        score = 0.0
        if mission.target_hex is not None:
            distance = target_hex.distance_to(mission.target_hex)
            score += weights["objective"] * (max(0.0, 12.0 - distance))
        score += weights["threat"] * threat
        score += weights["support"] * support
        score += self._movement_history_penalty(ctx, plan, mission, target_hex)
        score += self._front_direction_score(ctx, plan, mission, target_hex)
        score += self._front_congestion_score(ctx, plan, mission, target_hex)
        if territory_val == ctx.enemy:
            score += weights["capture"] * 6
        elif territory_val == ctx.side:
            score += 2

        loc = ctx.game_state.map.get_location(Hex.offset_to_axial(col, row))
        if loc and loc.occupier != ctx.side:
            score += 10

        # Defensive anchor rule:
        # if a ground group is already on the hex it is supposed to defend/reinforce,
        # strongly prefer holding that hex instead of stepping off it.
        if (
            mission.target_hex is not None
            and mission.group.has_army
            and mission.mission_type in {"defend", "defend_capital", "defend_allied_capital", "defend_key_location", "reinforce", "hold"}
            and current_hex == mission.target_hex
            and target_hex != current_hex
        ):
            hold_pressure = max(
                float(getattr(mission, "priority", 0.0) or 0.0) / 6.0,
                current_threat * 6.0,
            )
            score -= 70.0 + hold_pressure

            current_loc = ctx.game_state.map.get_location(current_hex)
            if current_loc and getattr(current_loc, "is_capital", False):
                score -= 40.0
            if current_loc and getattr(current_loc, "loc_type", None) in {LocType.FORTRESS.value, LocType.PORT.value, LocType.TEMPLE.value}:
                score -= 20.0
            if mission.objective and getattr(mission.objective, "coords", None) == current_hex.axial_to_offset():
                score -= 35.0
            if plan.main_objective and getattr(plan.main_objective, "coords", None) == current_hex.axial_to_offset():
                score -= 35.0

        # Do not peel the last combat defender off a friendly-controlled location.
        # This especially matters for air groups that would otherwise leave a leader
        # alone and unprotected on the hex.
        if (
            target_hex != current_hex
            and mission.mission_type in {"defend", "defend_capital", "defend_allied_capital", "defend_key_location", "reinforce", "hold"}
        ):
            current_loc = ctx.game_state.map.get_location(current_hex)
            if current_loc and getattr(current_loc, "occupier", None) == ctx.side:
                moving_markers = {id(u) for u in mission.group.units}
                remaining_friendly_combat = [
                    u for u in ctx.game_state.map.get_units_in_hex(current_hex.q, current_hex.r)
                    if u.allegiance == ctx.side
                    and u.is_on_map
                    and u.is_combat_unit()
                    and id(u) not in moving_markers
                ]
                if not remaining_friendly_combat:
                    score -= 140.0
                    if getattr(current_loc, "is_capital", False):
                        score -= 40.0
                    if getattr(current_loc, "loc_type", None) in {LocType.FORTRESS.value, LocType.PORT.value, LocType.TEMPLE.value}:
                        score -= 25.0
                if getattr(current_loc, "is_capital", False):
                    remaining_ground = len(_friendly_ground_combat_defenders_in_hex(ctx, current_hex, ctx.side)) - sum(
                        1 for u in mission.group.units if u.is_army() and u.is_combat_unit()
                    )
                    can_redeploy = _can_immediately_deploy_ground_defender(ctx, ctx.side, current_hex)
                    if remaining_ground < 1 and not can_redeploy:
                        score -= 400.0

        amphibious_types = {"embark_main_effort", "transport_main_effort", "move_to_landing_area"}
        if mission.mission_type in amphibious_types and plan.main_objective:
            # For FLEET transport missions: use assigned slot target, not a single global beachhead hex.
            if mission.mission_type == "transport_main_effort" and mission.group.has_fleet and (mission.target_hex or plan.beachhead_hex):
                assigned_target = mission.target_hex if mission.target_hex is not None else plan.beachhead_hex
                current_hex = mission.group.hex
                current_dist = current_hex.distance_to(assigned_target)
                next_dist = target_hex.distance_to(assigned_target)
                has_embarked_any = False
                for fleet_unit in mission.group.units:
                    if not fleet_unit.is_fleet():
                        continue
                    passengers = getattr(fleet_unit, "passengers", []) or []
                    if any(p.allegiance == ctx.side and p.is_army() for p in passengers):
                        has_embarked_any = True
                        break
                if not has_embarked_any:
                    return score
                
                # Reward movement toward assigned slot
                if next_dist < current_dist:
                    score += (current_dist - next_dist) * 20
                # Penalize movement away from assigned slot
                elif next_dist > current_dist:
                    score -= (next_dist - current_dist) * 15
                
                # Coastal/port bonuses
                if ctx.game_state.map.is_coastal(target_hex):
                    score += 8
                if loc and getattr(loc, "loc_type", None) == LocType.PORT.value:
                    score += 10
                
                # Penalize targets where current embarked armies cannot legally unboard.
                legal_unload_here = False
                for fleet_unit in mission.group.units:
                    if not fleet_unit.is_fleet():
                        continue
                    passengers = getattr(fleet_unit, "passengers", []) or []
                    for p in passengers:
                        if p.allegiance != ctx.side:
                            continue
                        if not p.is_army():
                            continue
                        if ctx.movement_service.can_unboard_unit_to_hex(p, target_hex):
                            legal_unload_here = True
                            break
                    if legal_unload_here:
                        break
                if not legal_unload_here:
                    score -= 50

                reserved = False
                for token in ctx.transport_actions_in_phase or set():
                    if isinstance(token, tuple) and len(token) >= 2 and token[0] == "landing_reserve":
                        if token[1] == target_hex.axial_to_offset():
                            reserved = True
                            break
                if reserved:
                    score -= 12
                
                # If at assigned slot with embarked troops, strongly prefer staying
                if current_hex == assigned_target and target_hex != current_hex:
                    score -= 30
            
            # Generic amphibious scoring for non-fleet transport (armies moving to embark, etc.)
            elif mission.group.has_fleet:
                main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
                current_dist = mission.group.hex.distance_to(main_hex)
                next_dist = target_hex.distance_to(main_hex)
                
                if next_dist < current_dist:
                    score += (current_dist - next_dist) * 15
                elif next_dist > current_dist:
                    score -= (next_dist - current_dist) * 12
                
                if ctx.game_state.map.is_coastal(target_hex):
                    score += 8
                if loc and getattr(loc, "loc_type", None) == LocType.PORT.value:
                    score += 10

        if mission.mission_type == "post_landing_push" and mission.target_hex is not None:
            current_hex = mission.group.hex
            current_dist = current_hex.distance_to(mission.target_hex)
            next_dist = target_hex.distance_to(mission.target_hex)
            if next_dist < current_dist:
                score += (current_dist - next_dist) * 18
            elif next_dist > current_dist:
                score -= (next_dist - current_dist) * 10

            beach_slots = list(plan.beachhead_slots or ([] if plan.beachhead_hex is None else [plan.beachhead_hex]))
            current_on_slot = any(current_hex == s for s in beach_slots)
            if ctx.game_state.map.is_coastal(target_hex):
                score -= 6
            if current_on_slot:
                if target_hex == current_hex:
                    score -= 18
                elif not ctx.game_state.map.is_coastal(target_hex):
                    score += 14
                else:
                    score -= 10
        if mission.mission_type == "secure_beachhead" and mission.target_hex is not None:
            current_hex = mission.group.hex
            current_dist = current_hex.distance_to(mission.target_hex)
            next_dist = target_hex.distance_to(mission.target_hex)
            if next_dist < current_dist:
                score += (current_dist - next_dist) * 10
            elif next_dist > current_dist:
                score -= (next_dist - current_dist) * 6
            if current_hex.distance_to(target_hex) <= 1:
                score += 8
            score += 6 * ctx.enemy_adjacent_combat_count.get((target_hex.q, target_hex.r), 0)

        if mission.mission_type == "prepare_assault" and mission.target_hex is not None:
            front_dist = target_hex.distance_to(mission.target_hex)
            if front_dist == 1:
                score += 24
            elif front_dist == 2:
                score += 12
            elif front_dist == 0:
                score -= 20

            # Avoid isolated forward staging on contested fronts.
            adj_friendly = ctx.friendly_adjacent_combat_count.get((target_hex.q, target_hex.r), 0)
            adj_enemy = ctx.enemy_adjacent_combat_count.get((target_hex.q, target_hex.r), 0)
            if front_dist <= 1 and adj_friendly < adj_enemy:
                score -= 18

        # Air support doctrine: avoid unsupported spearhead moves by air-only groups.
        if mission.group.has_wing and not mission.group.has_army and not mission.group.has_fleet:
            score += self._air_support_doctrine_score(ctx, plan, mission, target_hex)

        # Offensive mission scoring: STRICT anti-passivity
        offensive_types = {"push_objective", "main_effort_attack", "support_main_effort"}
        if mission.mission_type in offensive_types and plan.main_objective:
            main_hex = Hex.offset_to_axial(plan.main_objective.coords[0], plan.main_objective.coords[1])
            current_dist = current_hex.distance_to(main_hex)
            next_dist = target_hex.distance_to(main_hex)
            support_now = _overlay_value(friendly_power_overlay, current_col, current_row, 0.0)
            support_gain = support - support_now
            advance_gain = current_dist - next_dist

            # REWARD: Advancing toward the objective
            if advance_gain > 0:
                # Base reward for any forward progress
                score += advance_gain * 16
                # Bonus for meaningful advances (2+ hexes)
                if advance_gain >= 2:
                    score += 24
                # High urgency bonus: reward decisive movement
                if plan.must_act or plan.urgency_score >= 0.7:
                    score += 18
            # PENALTY: Lateral or backward moves
            else:
                pressure = 0.0
                if plan.must_act:
                    pressure += 18.0
                if plan.urgency_score >= 0.7:
                    pressure += 12.0
                if advance_gain == 0:
                    if support_gain <= 0:
                        # No progress AND no support gain = useless move
                        score -= 45 + pressure
                    else:
                        # Support gain alone doesn't justify no advance on offensive missions
                        score -= 10 + pressure * 0.5
                        score += min(2.0, support_gain)
                else:
                    retreat_penalty = 55 + abs(advance_gain) * 14 + pressure
                    if support_gain <= 0:
                        retreat_penalty += 12
                    score -= retreat_penalty
                    score += min(1.5, max(0.0, support_gain))

            # CRITICAL: Hard penalties under pressure
            if plan.must_act:
                if next_dist >= current_dist and support_gain <= 0:
                    score -= 50  # Must act + passive = unacceptable
            if plan.urgency_score >= 0.7:
                if next_dist >= current_dist:
                    score -= 35  # High urgency + no progress = bad
            # Deadline pressure: turns running out
            if plan.objective_deadline_turn is not None:
                turns_left = plan.objective_deadline_turn - ctx.turn
                if turns_left <= 3:
                    if next_dist >= current_dist:
                        score -= 55  # Critical deadline + passive = reject
                elif turns_left <= 5:
                    if next_dist >= current_dist and support_gain <= 0:
                        score -= 32
        return score

    @staticmethod
    def _air_support_doctrine_score(ctx: AIContext, plan: StrategicPlan, mission: Mission, target_hex: Hex) -> float:
        friendly_ground_hexes: List[Hex] = []
        for u in ctx.friendly_units:
            if not u.is_on_map:
                continue
            if u.transport_host is not None:
                continue
            if not u.is_army():
                continue
            if not u.position or None in u.position:
                continue
            friendly_ground_hexes.append(Hex.offset_to_axial(*u.position))

        nearest_ground_dist = min((target_hex.distance_to(h) for h in friendly_ground_hexes), default=99)
        target_stack = ctx.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
        enemy_combat = [
            u for u in target_stack
            if u.allegiance == ctx.enemy
            and u.is_on_map
            and u.is_combat_unit()
        ]
        enemy_power = sum(float(u.combat_rating) for u in enemy_combat)
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

    def _maybe_execute_transport_action(self, ctx: AIContext, plan: StrategicPlan, allow_commander_boarding: bool = True) -> Tuple[bool, bool]:
        """Execute transport actions in priority order: unboard, board commanders, board same-hex fleets."""
        transport_actions = ctx.transport_actions_in_phase
        beachhead_slots = list(plan.beachhead_slots or ([] if plan.beachhead_hex is None else [plan.beachhead_hex]))
        beachhead_slot_offsets = {h.axial_to_offset() for h in beachhead_slots}
        landed_state = set((ctx.invasion_state or {}).get("landed_armies", set()) or set())
        landed_leader_state = set((ctx.invasion_state or {}).get("landed_leaders", set()) or set())
        ashore_state = set((ctx.invasion_state or {}).get("ashore_committed_armies", set()) or set())
        
        # Stage 1: Batch fleet unloading wave.
        if plan.transport_campaign:
            # Fast guard: if nobody has embarked ground, unloading is impossible.
            any_embarked = any(
                u.is_fleet()
                and u.position and None not in u.position
                and TacticalPlanner._fleet_has_embarked_ground(u)
                for u in (ctx.friendly_units or [])
            )
            if any_embarked:
                unload_actions = self._collect_fleet_unload_actions(ctx, plan)
                if unload_actions:
                    debug_print(f"[TRANSPORT] unload_batch count={len(unload_actions)}")
                    unloaded_any = self._execute_fleet_unload_actions(ctx, plan, unload_actions, max_actions=4)
                    if unloaded_any:
                        return True, False

        # Stage 2: Board dragon commanders onto wings lacking them (CRITICAL for HL)
        commander_boarded = bool(allow_commander_boarding and self._board_dragon_commanders(ctx))

        # Stage 3: Same-hex fleet boarding for transport campaigns
        if plan.transport_campaign:
            board = ctx.game_state.map
            for fleet in ctx.friendly_units:
                if not fleet.is_fleet():
                    continue
                if not fleet.position or None in fleet.position:
                    continue

                fleet_hex = Hex.offset_to_axial(*fleet.position)
                stack = board.unit_map.get((fleet_hex.q, fleet_hex.r)) or []

                # Collect co-located friendly passengers, prioritizing ground armies
                candidates = []
                for unit in stack:
                    if unit is fleet:
                        continue
                    if unit.allegiance != ctx.side:
                        continue
                    if unit.transport_host is not None:
                        continue

                    # Build stable keys for transport memory
                    fleet_key = ("fleet", _unit_key(fleet))
                    passenger_key = ("passenger", _unit_key(unit))
                    pair_key = ("board", _unit_key(fleet), _unit_key(unit))
                    
                    # Skip if already tried this phase
                    if transport_actions and pair_key in transport_actions:
                        continue

                    # First priority: ground armies (only if fleet can carry)
                    if unit.is_army():
                        ukey = _unit_key(unit)
                        if ukey in ashore_state:
                            debug_print(f"[TRANSPORT] skip_reboard ashore_committed={getattr(unit, 'id', '?')}")
                            continue
                        if transport_actions and ("landed_army", ukey) in transport_actions:
                            debug_print(f"[TRANSPORT] skip_reboard landed={getattr(unit, 'id', '?')}")
                            continue
                        if ukey in landed_state:
                            debug_print(f"[TRANSPORT] skip_reboard landed={getattr(unit, 'id', '?')}")
                            continue
                        if unit.position and tuple(unit.position) in beachhead_slot_offsets:
                            debug_print(f"[TRANSPORT] skip_reboard beachhead={getattr(unit, 'id', '?')}")
                            continue
                        if ukey in landed_state and unit.position:
                            uhex = Hex.offset_to_axial(*unit.position)
                            if any(uhex.distance_to(slot) <= 1 for slot in beachhead_slots):
                                debug_print(f"[TRANSPORT] skip_reboard beachhead={getattr(unit, 'id', '?')}")
                            continue
                        if unit.moved_this_turn:
                            debug_print(f"[TRANSPORT] skip_reboard exhausted={getattr(unit, 'id', '?')}")
                            continue
                        if unit.movement_points <= 0:
                            debug_print(f"[TRANSPORT] skip_reboard exhausted={getattr(unit, 'id', '?')}")
                            continue
                        if fleet.can_carry(unit):
                            candidates.append((unit, 0, -float(getattr(unit, "combat_rating", 0) or 0), pair_key))

                    # Second priority: leaders (if fleet can carry)
                    elif unit.is_leader():
                        ukey = _unit_key(unit)
                        if transport_actions and ("landed_leader", ukey) in transport_actions:
                            debug_print(f"[TRANSPORT] skip_reboard landed_leader={getattr(unit, 'id', '?')}")
                            continue
                        if ukey in landed_leader_state:
                            debug_print(f"[TRANSPORT] skip_reboard landed_leader={getattr(unit, 'id', '?')}")
                            continue
                        if unit.position and tuple(unit.position) in beachhead_slot_offsets:
                            debug_print(f"[TRANSPORT] skip_reboard beachhead_leader={getattr(unit, 'id', '?')}")
                            continue
                        if fleet.can_carry(unit):
                            candidates.append((unit, 1, 0, pair_key))

                # Sort: armies first (priority 0), then by combat rating (stronger first)
                candidates.sort(key=lambda x: (x[1], x[2]))

                for passenger, _, _, pair_key in candidates:
                    if ctx.movement_service.board_unit(fleet, passenger):
                        if transport_actions is not None:
                            transport_actions.add(pair_key)
                        return True, commander_boarded

        return False, commander_boarded

    @staticmethod
    def _collect_fleet_unload_actions(ctx: AIContext, plan: StrategicPlan) -> List[Tuple[object, List[object], float]]:
        actions: List[Tuple[object, List[object], float]] = []
        projected_ground: Dict[Tuple[int, int], int] = {}
        threat = ctx.overlays.get("threat")
        selected_fleets: Set[Tuple[str, int]] = set()
        for unit in sorted(ctx.friendly_units, key=_unit_key):
            if not unit.is_fleet():
                continue
            if not getattr(unit, "position", None) or unit.position[0] is None:
                continue
            TacticalPlanner._debug_fleet_unload_state(ctx, plan, unit)
            passengers = list(getattr(unit, "passengers", []) or [])
            if not passengers:
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_no_embarked_ground")
                continue
            if not TacticalPlanner._fleet_has_embarked_ground(unit):
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_no_embarked_ground")
                continue
            fleet_hex = Hex.offset_to_axial(*unit.position)
            col, row = fleet_hex.axial_to_offset()
            key = (col, row)
            approved_slots = list(plan.beachhead_slots or ([] if plan.beachhead_hex is None else [plan.beachhead_hex]))
            assigned_offset = (plan.fleet_slot_assignments or {}).get(_unit_key(unit))
            if assigned_offset:
                approved_slots = [Hex.offset_to_axial(assigned_offset[0], assigned_offset[1])]
            if approved_slots and not any(fleet_hex == h for h in approved_slots):
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_not_on_slot")
                continue
            if key not in projected_ground:
                existing_ground = sum(
                    1 for u in ctx.game_state.map.get_units_in_hex(col, row)
                    if u.allegiance == ctx.side
                    and u.is_on_map
                    and u.is_army()
                )
                projected_ground[key] = existing_ground
            selected = TacticalPlanner._select_fleet_unboard_passengers(ctx, plan, unit, passengers)
            if not selected:
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_no_legal_passengers")
                continue
            cap = max(0, 2 - projected_ground[key])
            if cap <= 0:
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_slot_full")
                continue
            selected = selected[:cap]
            if not selected:
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_slot_full")
                continue
            projected_ground[key] += len(selected)
            assigned = False
            if assigned_offset and (int(assigned_offset[0]), int(assigned_offset[1])) == key:
                assigned = True
            strongest = max((float(p.combat_rating) for p in selected), default=0.0)
            threat_val = _overlay_value(threat, col, row, 0.0)
            slot_bonus = 25.0 if any(fleet_hex == h for h in (plan.beachhead_slots or [])) else 0.0
            assigned_bonus = 40.0 if assigned else 0.0
            score = assigned_bonus + slot_bonus + strongest * 2.0 - threat_val * 2.0
            actions.append((unit, selected, score))
            selected_fleets.add(_unit_key(unit))
        for unit in sorted(ctx.friendly_units, key=_unit_key):
            if not unit.is_fleet():
                continue
            if _unit_key(unit) not in selected_fleets and unit.position and None not in unit.position:
                debug_print(f"[TRANSPORT_UNLOAD_SKIP] fleet={getattr(unit, 'id', '?')} reason=skip_not_selected_in_batch")
        actions.sort(key=lambda item: item[2], reverse=True)
        return actions

    @staticmethod
    def _debug_fleet_unload_state(ctx: AIContext, plan: StrategicPlan, fleet):
        if not fleet.position or None in fleet.position:
            return
        fleet_hex = Hex.offset_to_axial(*fleet.position)
        col, row = fleet_hex.axial_to_offset()
        fleet_key = _unit_key(fleet)
        assigned_offset = (plan.fleet_slot_assignments or {}).get(fleet_key)
        assigned_hex = Hex.offset_to_axial(*assigned_offset) if assigned_offset else None
        approved_slots = list(plan.beachhead_slots or ([] if plan.beachhead_hex is None else [plan.beachhead_hex]))
        if assigned_hex is not None:
            approved_slots = [assigned_hex]
        on_assigned = bool(assigned_hex and fleet_hex == assigned_hex)
        on_approved = bool(any(fleet_hex == h for h in approved_slots))
        existing_ground = sum(
            1 for u in ctx.game_state.map.get_units_in_hex(col, row)
            if u.allegiance == ctx.side
            and u.is_on_map
            and u.is_army()
        )
        passengers = list(getattr(fleet, "passengers", []) or [])
        p_ids = [str(getattr(p, "id", "?")) for p in passengers]
        debug_print(
            f"[TRANSPORT_UNLOAD_CHECK] fleet={getattr(fleet, 'id', '?')} pos=({col},{row}) "
            f"assigned={(assigned_hex.axial_to_offset() if assigned_hex else None)} "
            f"on_assigned_slot={on_assigned} on_approved_slot={on_approved} existing_ground={existing_ground} passengers={p_ids}"
        )
        for p in passengers:
            legal_now = bool(ctx.movement_service.can_unboard_unit_to_hex(p, fleet_hex))
            debug_print(f"[TRANSPORT_UNLOAD_PASSENGER] fleet={getattr(fleet, 'id', '?')} passenger={getattr(p, 'id', '?')} legal_now={legal_now}")

    def _execute_fleet_unload_actions(
        self,
        ctx: AIContext,
        plan: StrategicPlan,
        actions: List[Tuple[object, List[object], float]],
        max_actions: int = 4,
    ) -> bool:
        if not actions:
            return False
        transport_actions = ctx.transport_actions_in_phase
        landed_state = set((ctx.invasion_state or {}).get("landed_armies", set()) or set())
        landed_leader_state = set((ctx.invasion_state or {}).get("landed_leaders", set()) or set())
        ashore_state = set((ctx.invasion_state or {}).get("ashore_committed_armies", set()) or set())
        unloaded = 0
        for fleet, selected, _score in actions:
            if unloaded >= max_actions:
                break
            if not fleet.position or None in fleet.position:
                continue
            fleet_hex = Hex.offset_to_axial(*fleet.position)
            col, row = fleet_hex.axial_to_offset()
            if not self._unboard_all(ctx, fleet, selected):
                continue
            unloaded += 1
            unit_ids = [str(getattr(p, "id", "?")) for p in selected]
            debug_print(f"[TRANSPORT] unload_exec fleet={getattr(fleet, 'id', '?')} slot=({col},{row}) units={unit_ids}")
            if transport_actions is not None:
                transport_actions.add(("landing_reserve", (col, row)))
                for p in selected:
                    transport_actions.add(("landing_unload", _unit_key(fleet), (col, row)))
                    if p.is_army():
                        transport_actions.add(("landed_army", _unit_key(p)))
                        landed_state.add(_unit_key(p))
                        ashore_state.add(_unit_key(p))
                        debug_print(f"[TRANSPORT] ashore_committed={getattr(p, 'id', '?')}")
                    elif p.is_leader():
                        transport_actions.add(("landed_leader", _unit_key(p)))
                        landed_leader_state.add(_unit_key(p))
            if ctx.invasion_state is not None:
                ctx.invasion_state["landed_armies"] = set(landed_state)
                ctx.invasion_state["landed_leaders"] = set(landed_leader_state)
                ctx.invasion_state["ashore_committed_armies"] = set(ashore_state)
        return unloaded > 0

    @staticmethod
    def _select_fleet_unboard_passengers(ctx: AIContext, plan: StrategicPlan, fleet, passengers: List[object]) -> List[
        object]:
        """Select passengers to unboard from fleet on assigned/approved beachhead slots.

        Ground armies drive the landing decision and count against the landing density cap.
        Friendly leaders on the same fleet are treated as companion passengers:
        - they unload together with the selected army/armies when legal
        - they do NOT count against the army landing density cap
        - they do NOT unload alone if no army is unloading
        """
        if not plan.main_objective or not fleet.position or None in fleet.position:
            return []

        fleet_hex = Hex.offset_to_axial(*fleet.position)
        col, row = fleet_hex.axial_to_offset()

        assigned_slot = None
        fleet_id_key = _unit_key(fleet)
        offset = (plan.fleet_slot_assignments or {}).get(fleet_id_key)
        if offset:
            assigned_slot = Hex.offset_to_axial(offset[0], offset[1])

        approved_slots = list(plan.beachhead_slots or [])
        if assigned_slot is not None:
            approved_slots = [assigned_slot]
        elif not approved_slots and plan.beachhead_hex is not None:
            approved_slots = [plan.beachhead_hex]

        # Fleet must already be on its assigned/approved unload slot.
        if not approved_slots or not any(fleet_hex == h for h in approved_slots):
            return []

        # 1) Select candidate ground armies only (they drive landing legality / density).
        candidate_armies = [p for p in passengers if p.allegiance == ctx.side and p.is_army()]
        if not candidate_armies:
            return []

        legal_hexes = []
        seen_hexes = set()
        for p in candidate_armies:
            for h in ctx.movement_service.get_valid_unboard_hexes(fleet, p):
                key = (h.q, h.r)
                if key in seen_hexes:
                    continue
                seen_hexes.add(key)
                legal_hexes.append(h)

        if not any(h == fleet_hex for h in legal_hexes):
            debug_print(f"[TRANSPORT] no_legal_unload_hex at ({col},{row})")
            return []

        legal_now_armies = [
            p for p in candidate_armies
            if ctx.movement_service.can_unboard_unit_to_hex(p, fleet_hex)
        ]
        if not legal_now_armies:
            debug_print(f"[TRANSPORT] unload_illegal at ({col},{row})")
            return []

        # 2) Landing density cap applies to GROUND ARMIES only.
        existing_ground = sum(
            1 for u in ctx.game_state.map.get_units_in_hex(col, row)
            if u.allegiance == ctx.side
            and u.is_on_map
            and u.is_army()
        )
        if existing_ground >= 2:
            return []

        max_unload_armies = 2 - existing_ground
        selected_armies = list(legal_now_armies)
        selected_armies.sort(
            key=lambda u: (float(getattr(u, "combat_rating", 0) or 0), _unit_key(u)),
            reverse=True,
        )
        selected_armies = selected_armies[:max_unload_armies]

        # IMPORTANT: never unload leaders alone.
        if not selected_armies:
            return []

        # 3) Add companion leaders from the same fleet if they can legally unboard here.
        companion_leaders = [
            p for p in passengers
            if p.allegiance == ctx.side
               and p.is_leader()
               and ctx.movement_service.can_unboard_unit_to_hex(p, fleet_hex)
        ]

        for leader in companion_leaders:
            debug_print(f"[TRANSPORT] companion_leader_unload={getattr(leader, 'id', '?')} fleet={getattr(fleet, 'id', '?')}")

        return selected_armies + companion_leaders

    def _board_dragon_commanders(self, ctx: AIContext) -> bool:
        """Board eligible leaders onto dragon wings that lack a commander.
        
        For HL: same-flight Highlord preferred, Emperor fallback.
        For WS: equivalent valid commander logic.
        """
        boarded_any = False
        wings = sorted(
            [
                u for u in ctx.friendly_units
                if u.is_wing() and u.is_dragon()
                and u.is_on_map
                and u.transport_host is None
                and u.position and None not in u.position
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
                if u.allegiance == ctx.side
                and u.is_leader()
                and u.is_on_map
                and u.transport_host is None
            ]
            if not leaders:
                continue
            commander = self._select_dragon_commander_for_wing(ctx, wing, leaders)
            if commander and ctx.movement_service.board_unit(wing, commander):
                boarded_any = True
        return boarded_any

    @staticmethod
    def _wing_has_valid_dragon_commander(ctx: AIContext, wing) -> bool:
        passengers = list(getattr(wing, "passengers", []) or [])
        if not passengers:
            return False
        if wing.allegiance == HL:
            for p in passengers:
                if p.unit_type == UnitType.EMPEROR:
                    return True
                if p.unit_type != UnitType.HIGHLORD:
                    continue
                p_flight = str(getattr(getattr(p, "spec", None), "dragonflight", "") or "").strip().lower()
                wing_flight = str(getattr(getattr(wing, "spec", None), "dragonflight", "") or "").strip().lower()
                if p_flight and p_flight == wing_flight:
                    return True
            return False
        if wing.allegiance == WS:
            return any(p.race in (UnitRace.SOLAMNIC, UnitRace.ELF) for p in passengers)
        return any(p.is_leader() for p in passengers)

    @staticmethod
    def _select_dragon_commander_for_wing(ctx: AIContext, wing, leaders: List[object]) -> Optional[object]:
        if wing.allegiance == HL:
            return TacticalPlanner._select_hl_dragon_commander(wing, leaders)
        if wing.allegiance == WS:
            ws = [l for l in leaders if l.race in (UnitRace.SOLAMNIC, UnitRace.ELF)]
            if ws:
                return sorted(ws, key=_unit_key)[0]
        fallback = [l for l in leaders if l.is_leader()]
        return sorted(fallback, key=_unit_key)[0] if fallback else None

    @staticmethod
    def _unboard_all(ctx: AIContext, carrier, passengers: List[object]) -> bool:
        moved = False
        carrier_hex = None
        if carrier.position and None not in carrier.position:
            carrier_hex = Hex.offset_to_axial(*carrier.position)
        for p in list(passengers):
            if carrier_hex is not None and carrier.is_fleet():
                if not ctx.movement_service.can_unboard_unit_to_hex(p, carrier_hex):
                    col, row = carrier_hex.axial_to_offset()
                    debug_print(f"[TRANSPORT] unload_illegal at ({col},{row})")
                    continue
            if ctx.movement_service.unboard_unit(p):
                debug_print(f"[TRANSPORT] Unboarded {getattr(p, 'id', '?')} from {getattr(carrier, 'id', '?')}")
                moved = True
            elif carrier_hex is not None and carrier.is_fleet():
                col, row = carrier_hex.axial_to_offset()
                debug_print(f"[TRANSPORT] unload_illegal at ({col},{row})")
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
            if all(u.attacked_this_turn for u in group.units):
                continue
            for neighbor in group.hex.neighbors():
                if (neighbor.q, neighbor.r) in failed_targets:
                    continue
                defenders = board.get_units_in_hex(neighbor.q, neighbor.r)
                defenders = [u for u in defenders if u.allegiance == ctx.enemy and u.is_on_map]
                if not defenders:
                    continue
                if not ctx.game_state.combat_service.can_units_attack_stack(group.units, defenders):
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
                    if u.is_on_map
                    and not u.attacked_this_turn
                ]
                if not attackers:
                    continue
                if not ctx.game_state.combat_service.can_units_attack_stack(attackers, defenders):
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
        attackers = [u for u in best["attackers"] if u.is_on_map]
        defenders_before = list(ctx.game_state.get_units_at(target_hex))
        resolution = ctx.game_state.combat_service.resolve_combat(attackers, target_hex)
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
            ctx.game_state.combat_service.advance_after_combat(attackers, target_hex)
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
            float(u.combat_rating)
            for u in group.units
            if u.is_combat_unit()
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
        att_power = sum(float(u.combat_rating) for u in attackers if u.is_combat_unit())
        def_power = sum(float(u.combat_rating) for u in defenders if u.is_combat_unit())
        if att_power <= 0 or def_power <= 0:
            return {"allow": False, "note": "no_combat_power"}

        projected_odds_str = None
        projected_ratio = None
        combat_service = getattr(ctx.game_state, "combat_service", None)
        if combat_service:
            try:
                if hasattr(combat_service, "calculate_odds_ratio"):
                    projected_ratio = combat_service.calculate_odds_ratio(attackers, defenders, target_hex)
                if hasattr(combat_service, "calculate_odds_preview"):
                    projected_odds_str = combat_service.calculate_odds_preview(attackers, defenders, target_hex)
            except Exception:
                projected_odds_str = None
                projected_ratio = None

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
        if offensive and ctx.side == HL and str(plan.victory_category or "").lower() == "control":
            min_odds -= 0.1
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

        defensive_desperate_recovery = False
        if not offensive:
            defensive_desperate_recovery = self._is_desperate_defensive_recovery_attack(ctx, target_hex)
            if projected_ratio is not None and projected_ratio < 2.0 and not defensive_desperate_recovery:
                return {
                    "allow": False,
                    "note": "defensive_crt_2to1_gate",
                    "odds": odds,
                    "projected_odds": projected_odds_str,
                    "projected_ratio": projected_ratio,
                }

        air_combat = [u for u in attackers if u.is_combat_unit()]
        ground_present = any(u.is_army() for u in air_combat)
        air_only = bool(air_combat) and not ground_present and any(u.is_wing() or u.is_citadel() for u in air_combat)
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
            "projected_odds": projected_odds_str,
            "projected_ratio": projected_ratio,
            "defensive_desperate_recovery": defensive_desperate_recovery,
        }

    @staticmethod
    def _collect_capture_locations_with_deadline(raw: Any, current_turn: int, default_deadline: int, out: Set[str]):
        if isinstance(raw, dict):
            if "all" in raw:
                for child in raw.get("all", []) or []:
                    TacticalPlanner._collect_capture_locations_with_deadline(child, current_turn, default_deadline, out)
            if "any" in raw:
                for child in raw.get("any", []) or []:
                    TacticalPlanner._collect_capture_locations_with_deadline(child, current_turn, default_deadline, out)
            node_type = str(raw.get("type", "") or "")
            if node_type == "capture_location":
                try:
                    by_turn = int(raw.get("by_turn")) if raw.get("by_turn") is not None else None
                except Exception:
                    by_turn = None
                if by_turn is None:
                    by_turn = int(default_deadline or 0) if default_deadline else None
                if by_turn is not None and by_turn <= current_turn:
                    loc_id = _slugify(raw.get("location", ""))
                    if loc_id:
                        out.add(loc_id)
            return
        if isinstance(raw, list):
            for child in raw:
                TacticalPlanner._collect_capture_locations_with_deadline(child, current_turn, default_deadline, out)

    def _is_desperate_defensive_recovery_attack(self, ctx: AIContext, target_hex: Hex) -> bool:
        end_turn = int(getattr(ctx.game_state.scenario_spec, "end_turn", 0) or 0)
        if end_turn <= 0 or ctx.turn != end_turn:
            return False

        victory_eval = getattr(ctx.game_state, "victory_evaluator", None)
        if victory_eval is None:
            return False
        status = victory_eval.evaluate()
        if getattr(status, "major_winner", None) != ctx.enemy:
            return False

        target_loc = ctx.game_state.map.get_location(target_hex)
        target_loc_id = _slugify(getattr(target_loc, "id", "") or "")
        if not target_loc_id:
            return False

        vc = getattr(ctx.game_state.scenario_spec, "victory_conditions", {}) or {}
        enemy_major = (vc.get(ctx.enemy, {}) or {}).get("major")
        if not enemy_major:
            return False

        urgent_capture_locations: Set[str] = set()
        self._collect_capture_locations_with_deadline(enemy_major, ctx.turn, end_turn, urgent_capture_locations)
        if target_loc_id not in urgent_capture_locations:
            return False

        return bool(getattr(target_loc, "occupier", None) == ctx.enemy)

    @staticmethod
    def _is_air_special_opportunity(ctx: AIContext, target_hex: Hex, defenders: List[object], is_main_objective_hex: bool) -> bool:
        def_power = sum(
            float(getattr(u, "combat_rating", 0) or 0)
            for u in defenders
            if u.is_combat_unit()
        )
        loc = ctx.game_state.map.get_location(target_hex)
        weak_enemy_location = bool(loc and getattr(loc, "occupier", None) == ctx.enemy and def_power <= 3.0)
        return weak_enemy_location or (is_main_objective_hex and def_power <= 2.0)

    @staticmethod
    def _crossing_attack_penalty(ctx: AIContext, attackers: List[object], target_hex: Hex) -> float:
        penalty = 0.0
        for u in attackers:
            if not u.is_army():
                continue
            src = Hex.offset_to_axial(*u.position)
            if target_hex not in src.neighbors():
                continue
            edge = ctx.game_state.map.get_effective_hexside(src, target_hex)
            if edge in (HexsideType.RIVER, HexsideType.BRIDGE):
                penalty += 1.0
            elif edge == HexsideType.FORD:
                penalty += 0.7
            elif edge == HexsideType.PASS:
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
        defenders_power = sum(float(u.combat_rating) for u in defenders if u.is_combat_unit())
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
        att_power = sum(float(u.combat_rating) for u in group.units if u.is_combat_unit())
        def_power = sum(float(u.combat_rating) for u in defenders if u.is_combat_unit())
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
        self._transport_phase_key = None
        self._beachhead_phase_key = None
        self._beachhead_by_side_in_phase = {}
        self._transport_actions_in_phase = set()
        self._invasion_state_by_side: Dict[str, Dict[str, Any]] = {}
        self._movement_phase_plan_cache_by_side: Dict[str, Dict[str, Any]] = {}
        self._neutral_front_cache_by_side: Dict[str, Dict[str, Any]] = {}
        self._static_geo_cache_scenario_id: Optional[str] = None
        self._country_hexes_by_id_cache: Optional[Dict[str, List[Hex]]] = None
        self._country_port_counts_cache: Optional[Dict[str, int]] = None
        self._coastal_hexes_cache: Optional[List[Hex]] = None
        self._country_id_by_offset_cache: Optional[Dict[Tuple[int, int], str]] = None
        self._unit_last_position: Dict[Tuple[str, int], Tuple[int, int]] = {}
        self._movement_history_by_side: Dict[str, Dict[Tuple[Tuple[str, int], ...], Dict[str, Any]]] = defaultdict(dict)
        self._failed_combat_targets = defaultdict(set)
        self._moved_task_groups_in_phase: set = set()
        self._front_diag_logged_phase: Set[Tuple[Any, ...]] = set()
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
        if (
            getattr(self.game_state, "phase", None) == GamePhase.DEPLOYMENT
            and not allow_territory_wide
            and country_filter is None
            and not invasion_deployment_active
        ):
            deployed = self.game_state.apply_canonical_deployment(side)
            if deployed is not None:
                self._log(f"deploy: {deployed} units (canonical)")
                return deployed

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
                if u.allegiance == side
                and u.status == UnitState.RESERVE
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
            int(unit.combat_rating),
            int(unit.movement),
            str(unit.id),
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

            align_score = _country_alignment_for_side(country, side) * 10.0
            objective_score = 0.0
            for obj in plan.objectives[:8]:
                if obj.country_id == country.id:
                    objective_score += obj.value

            frontier_count, min_dist = self._strategic._country_frontier_metrics(ctx, country.id)

            score = 0.0
            score += attempt.target_rating * 12.0
            score += align_score
            score += objective_score

            # Prefer activation for countries that are NOT the immediate conquest front.
            if side == HL:
                if country.id == getattr(plan, "invasion_target", None):
                    score -= 140.0
                elif frontier_count > 0:
                    score -= 80.0
                else:
                    # Favor non-frontline but diplomatically promising countries.
                    score += max(0.0, 12.0 - float(min_dist)) * 2.0
                    score += 20.0

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
            return False, translator.get_country_name(best.id)

        self.diplomacy_service.activate_country(best.id, side)
        deployed = self.deploy_all_ready_units(side, allow_territory_wide=True, country_filter=best.id)
        self._log(f"activation success: {best.id} deployed={deployed}")
        return True, translator.get_country_name(best.id)

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

        units = [u for u in ctx.friendly_units if u.is_on_map]
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
        """Trigger neutral invasion only for the selected target, using the same
        force eligibility and odds baseline as movement+diplomacy services."""
        if not attempt_invasion:
            return False

        target_country_id = getattr(plan, "invasion_target", None)
        if not target_country_id:
            return False

        target_country = ctx.game_state.countries.get(target_country_id)
        if not target_country:
            return False

        probe_hexes = list((ctx.country_hexes_by_id or {}).get(target_country_id, []))
        if not probe_hexes:
            return False

        probe = ctx.movement_service.invasion_handler.evaluate_neutral_entry(probe_hexes[0])
        if not probe or not getattr(probe, "is_neutral_entry", False):
            return False
        if getattr(probe, "blocked_message", None):
            debug_print(f"[INVASION] Delaying invasion of {target_country_id}: {probe.blocked_message}")
            return False

        invasion_data = ctx.movement_service.get_invasion_force(target_country_id)
        invader_sp = int(invasion_data.get("strength", 0) or 0)
        if invader_sp <= 0:
            reason = invasion_data.get("reason") or "No eligible invasion force."
            debug_print(f"[INVASION] Delaying invasion of {target_country_id}: {reason}")
            return False

        defender_sp = int(getattr(target_country, "strength", 0) or 0)
        modifier = self.diplomacy_service._invasion_modifier(invader_sp, defender_sp)
        alignment = getattr(target_country, "alignment", (0, 0)) or (0, 0)
        ws_base = int(alignment[0] if len(alignment) > 0 else 0) + 2
        hl_base = int(alignment[1] if len(alignment) > 1 else 0) + modifier
        force_ratio = invader_sp / max(defender_sp, 1)

        required_edge = 2
        if force_ratio >= 2:
            required_edge = 1
        if force_ratio >= 2.5:
            required_edge = -10
        # if invader_sp >= defender_sp * 2 and defender_sp > 0:
        #     required_edge = 1
        # Require a clear Highlord edge; neutral odds are too wasteful for AI expansion.
        if hl_base < ws_base + required_edge:
            debug_print(
                f"[INVASION] Delaying invasion of {target_country_id}: "
                f"hl_base={hl_base} ws_base={ws_base} required_edge={required_edge} "
                f"invader_sp={invader_sp} defender_sp={defender_sp}"
            )
            return False

        debug_print(
            f"[INVASION] Triggering invasion of {target_country_id}: "
            f"hl_base={hl_base} ws_base={ws_base} required_edge={required_edge} "
            f"invader_sp={invader_sp} defender_sp={defender_sp}"
        )
        attempt_invasion(target_country_id)
        post_country = ctx.game_state.countries.get(target_country_id)
        if post_country and getattr(post_country, "allegiance", None) != NEUTRAL:
            return True
        debug_print(f"[INVASION] Invasion of {target_country_id} did not change allegiance; falling through to movement.")
        return False

    # ---------- Movement ----------
    def execute_best_movement(self, side: str, attempt_invasion=None) -> bool:
        t0 = perf_counter()
        moved_groups = self._ensure_movement_phase_memory()
        ctx = self._build_context(side, moved_task_groups=moved_groups)
        t1 = perf_counter()
        phase_key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
            side,
        )
        cache = self._movement_phase_plan_cache_by_side.get(side)
        state = ctx.invasion_state or {}
        state_objective_id = str(state.get("primary_objective_id") or "")
        state_version = int(state.get("version", 0) or 0)
        transport_signature = self._compute_transport_signature(ctx)
        transport_actions_count = len(ctx.transport_actions_in_phase or set())

        reuse_cached = False
        recompute_reason = "no_cache"
        if cache and cache.get("phase_key") == phase_key:
            if str(cache.get("objective_id") or "") != state_objective_id:
                recompute_reason = "objective_changed"
            elif int(cache.get("invasion_version", 0) or 0) != state_version:
                recompute_reason = "landing_version_changed"
            elif cache.get("transport_signature") != transport_signature:
                recompute_reason = "transport_state_changed"
            elif int(cache.get("transport_actions_count", -1)) != transport_actions_count:
                recompute_reason = "transport_actions_changed"
            elif not self._cached_slots_still_valid(ctx, cache):
                recompute_reason = "slots_invalid"
            else:
                reuse_cached = True
        else:
            recompute_reason = "phase_or_cache_miss"

        if reuse_cached:
            plan = cache.get("plan")
            debug_print(f"[TRANSPORT] phase_plan_reused side={side} objective={cache.get('objective_id')}")
        else:
            plan = self._strategic.build_plan(ctx)
            self._update_invasion_state_from_plan(side, plan)
            updated_state = self._get_invasion_state(side)
            self._movement_phase_plan_cache_by_side[side] = {
                "phase_key": phase_key,
                "plan": plan,
                "objective_id": str(getattr(plan.main_objective, "id", "") or ""),
                "invasion_version": int(updated_state.get("version", 0) or 0),
                "beachhead_hex": plan.beachhead_hex.axial_to_offset() if plan.beachhead_hex is not None else None,
                "beachhead_slots": [h.axial_to_offset() for h in (plan.beachhead_slots or [])],
                "fleet_slot_assignments": dict(plan.fleet_slot_assignments or {}),
                "transport_signature": transport_signature,
                "transport_actions_count": transport_actions_count,
            }
            debug_print(f"[TRANSPORT] phase_plan_recomputed reason={recompute_reason}")
        t2 = perf_counter()
        ctx.front_analysis = self._build_front_analysis(ctx, plan)
        groups = self._operational.build_task_groups(ctx)
        t3 = perf_counter()
        missions = self._operational.build_missions(ctx, plan, groups)
        t4 = perf_counter()
        self._log_front_diagnostics(ctx, plan)
        
        # Debug print for transport: show objective vs beachhead separation
        if plan.transport_campaign:
            if plan.main_objective:
                obj_col, obj_row = plan.main_objective.coords
                debug_print(f"[TRANSPORT] objective=({obj_col},{obj_row})")
            if plan.beachhead_hex:
                col, row = plan.beachhead_hex.axial_to_offset()
                debug_print(f"[TRANSPORT] beachhead=({col},{row})")
        
        # Neutral invasion override
        if self._try_neutral_invasion(ctx, plan, attempt_invasion):
            target_country_id = getattr(plan, "invasion_target", None)
            post_country = ctx.game_state.countries.get(target_country_id) if target_country_id else None
            post_allegiance = getattr(post_country, "allegiance", None) if post_country is not None else None
            if post_allegiance == side:
                self._movement_phase_plan_cache_by_side.pop(side, None)
                cache = self._neutral_front_cache_by_side.get(side)
                if cache is not None:
                    cache["invasion_target"] = None
                    cache["staging_hexes"] = None
                debug_print(
                    f"[INVASION] invalidating_cached_plan country={target_country_id} "
                    f"post_allegiance={post_allegiance}"
                )
            else:
                debug_print(
                    f"[INVASION] keeping_cached_plan country={target_country_id} "
                    f"post_allegiance={post_allegiance}"
                )
            t5 = perf_counter()
            self._log(
                "movement_timing "
                f"context={((t1 - t0) * 1000):.1f}ms "
                f"plan={((t2 - t1) * 1000):.1f}ms "
                f"groups={((t3 - t2) * 1000):.1f}ms "
                f"missions={((t4 - t3) * 1000):.1f}ms "
                f"tactical={((t5 - t4) * 1000):.1f}ms "
                f"total={((t5 - t0) * 1000):.1f}ms "
                f"groups_n={len(groups)} missions_n={len(missions)} cache_reused={reuse_cached}"
            )
            return True
        
        # Keep neutral invasion centralized in _try_neutral_invasion to avoid invalid popup churn.
        moved = self._tactical.execute_best_movement(ctx, plan, missions, attempt_invasion=None)
        t5 = perf_counter()
        if moved:
            self._log(f"movement: executed ({plan.posture})")
            for line in ctx.movement_logs:
                self._log(line)
        self._log(
            "movement_timing "
            f"context={((t1 - t0) * 1000):.1f}ms "
            f"plan={((t2 - t1) * 1000):.1f}ms "
            f"groups={((t3 - t2) * 1000):.1f}ms "
            f"missions={((t4 - t3) * 1000):.1f}ms "
            f"tactical={((t5 - t4) * 1000):.1f}ms "
            f"total={((t5 - t0) * 1000):.1f}ms "
            f"groups_n={len(groups)} missions_n={len(missions)} cache_reused={reuse_cached}"
        )
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
        objective_graph_obj = ObjectiveAnalyzer.extract_objective_graph(self.game_state, side)
        objective_graph = {
            "offensive_target_countries": set(objective_graph_obj.offensive_target_countries),
            "defensive_target_countries": set(objective_graph_obj.defensive_target_countries),
            "offensive_target_locations": set(objective_graph_obj.offensive_target_locations),
            "defensive_target_locations": set(objective_graph_obj.defensive_target_locations),
            "enemy_offensive_countries": set(objective_graph_obj.enemy_offensive_countries),
            "enemy_offensive_locations": set(objective_graph_obj.enemy_offensive_locations),
            "country_importance": dict(objective_graph_obj.country_importance),
            "location_importance": dict(objective_graph_obj.location_importance),
            "deadline_turn": objective_graph_obj.deadline_turn,
        }
        invasion_state = self._get_invasion_state(side)
        country_hexes_by_id = self._get_country_hexes_by_id()
        country_port_counts = self._get_country_port_counts()
        coastal_hexes = self._get_coastal_hexes()
        country_id_by_offset = self._get_country_id_by_offset()
        neutral_front_cache = self._get_neutral_front_cache(side)
        objectives = self._collect_objectives(side, objective_graph=objective_graph)
        friendly_units = [u for u in self.game_state.units if u.allegiance == side and u.is_on_map]
        enemy_units = [u for u in self.game_state.units if u.allegiance == enemy and u.is_on_map]
        embarked_ground = [
            p for u in friendly_units
            if u.is_fleet()
            for p in (u.passengers or [])
            if p.is_army() and p.allegiance == side
        ]
        self._prune_ashore_committed_state(side)
        for u in friendly_units:
            self._clear_landed_flag_if_inland(side, u)
            self._clear_ashore_committed_flag_if_explicitly_retasked(side, u)
        enemy_adjacent_combat_count, friendly_adjacent_combat_count = self._build_adjacent_combat_maps(
            friendly_units=friendly_units,
            enemy_units=enemy_units,
        )
        
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
            transport_actions_in_phase=self._ensure_transport_phase_memory(),
            objective_graph=objective_graph,
            invasion_state=invasion_state,
            country_hexes_by_id=country_hexes_by_id,
            country_port_counts=country_port_counts,
            coastal_hexes=coastal_hexes,
            country_id_by_offset=country_id_by_offset,
            neutral_front_cache=neutral_front_cache,
            embarked_ground=embarked_ground,
            enemy_adjacent_combat_count=enemy_adjacent_combat_count,
            friendly_adjacent_combat_count=friendly_adjacent_combat_count,
            movement_history=self._movement_history_by_side[side],
        )

    @staticmethod
    def _build_adjacent_combat_maps(friendly_units: List[object], enemy_units: List[object]) -> Tuple[Dict[Tuple[int, int], int], Dict[Tuple[int, int], int]]:
        def combat_hexes(units: List[object]) -> Set[Tuple[int, int]]:
            out: Set[Tuple[int, int]] = set()
            for unit in units:
                if not unit.is_combat_unit():
                    continue
                if not unit.position or unit.position[0] is None or unit.position[1] is None:
                    continue
                h = Hex.offset_to_axial(*unit.position)
                out.add((h.q, h.r))
            return out

        def adjacent_counts(source_hexes: Set[Tuple[int, int]]) -> Dict[Tuple[int, int], int]:
            counts: Dict[Tuple[int, int], int] = defaultdict(int)
            for q, r in source_hexes:
                for neighbor in Hex(q, r).neighbors():
                    counts[(neighbor.q, neighbor.r)] += 1
            return dict(counts)

        enemy_hexes = combat_hexes(enemy_units)
        friendly_hexes = combat_hexes(friendly_units)
        return adjacent_counts(enemy_hexes), adjacent_counts(friendly_hexes)

    def _build_front_analysis(self, ctx: AIContext, plan: StrategicPlan) -> Dict[str, Any]:
        facts = ctx.control_facts
        occupied = getattr(facts, "occupied", {}) or {}
        zoc_by_side = getattr(facts, "zoc_by_side", {}) or {}
        friendly_occ = {coord for coord, side in occupied.items() if side == ctx.side}
        enemy_occ = {coord for coord, side in occupied.items() if side == ctx.enemy}
        enemy_pressure = set(enemy_occ)
        enemy_pressure.update(zoc_by_side.get(ctx.enemy, set()) or set())
        enemy_pressure.update(set(ctx.enemy_adjacent_combat_count.keys()))

        hot_front = set()
        for q, r in friendly_occ:
            here = Hex(q, r)
            if (q, r) in enemy_pressure:
                hot_front.add((q, r))
                continue
            if any((n.q, n.r) in enemy_pressure for n in here.neighbors()):
                hot_front.add((q, r))

        territory = ctx.overlays.get("territory")
        target_country_ids = set((ctx.objective_graph or {}).get("offensive_target_countries", set()) or set())
        if getattr(plan.main_objective, "country_id", None):
            target_country_ids.add(str(plan.main_objective.country_id))
        friendly_mobile_hexes = [
            Hex.offset_to_axial(*unit.position)
            for unit in ctx.friendly_units
            if unit.is_on_map
            and unit.position
            and unit.position[0] is not None
            and (unit.is_army() or unit.is_wing())
        ]

        expansion_rows: List[Dict[str, Any]] = []
        cold_rows: List[Dict[str, Any]] = []
        for country in ctx.game_state.countries.values():
            cid = str(getattr(country, "id", "") or "")
            if not cid:
                continue
            allegiance = getattr(country, "allegiance", None)
            if allegiance == ctx.side:
                continue
            hexes = list((ctx.country_hexes_by_id or {}).get(cid, []) or [])
            if not hexes:
                continue

            frontier_count = 0
            seen_frontier: Set[Tuple[int, int]] = set()
            min_dist = 999
            for h in hexes:
                for n in h.neighbors():
                    ncol, nrow = n.axial_to_offset()
                    if not ctx.game_state.is_hex_in_bounds(ncol, nrow):
                        continue
                    if (n.q, n.r) in friendly_occ:
                        seen_frontier.add((n.q, n.r))
                    elif territory and territory.values.get((ncol, nrow)) == ctx.side:
                        seen_frontier.add((n.q, n.r))
                for unit_hex in friendly_mobile_hexes:
                    min_dist = min(min_dist, unit_hex.distance_to(h))
            frontier_count = len(seen_frontier)

            objective_bonus = 40 if cid in target_country_ids else 0
            alignment = _country_alignment_for_side(country, ctx.side)
            strength = float(getattr(country, "strength", 0) or 0)
            distance_bonus = max(0, 12 - min_dist) * 4
            score = frontier_count * 25 + objective_bonus + alignment * 2 + distance_bonus - strength * 0.8
            row = {
                "score": score,
                "country_id": cid,
                "frontier_count": frontier_count,
                "min_dist": min_dist,
                "allegiance": allegiance,
            }
            if allegiance == NEUTRAL and frontier_count > 0:
                expansion_rows.append(row)
            elif allegiance != ctx.side:
                cold_rows.append(row)

        expansion_rows.sort(key=lambda r: float(r.get("score", 0.0)), reverse=True)
        cold_rows.sort(key=lambda r: float(r.get("score", 0.0)), reverse=True)
        cold_front_rows = [r for r in cold_rows if int(r.get("frontier_count", 0) or 0) > 0]
        primary = expansion_rows[0] if expansion_rows else (cold_front_rows[0] if cold_front_rows else None)
        return {
            "hot_count": len(hot_front),
            "enemy_pressure_count": len(enemy_pressure),
            "expansion": expansion_rows,
            "cold": cold_rows,
            "primary_country_id": primary.get("country_id") if primary else None,
            "primary_mode": "expansion" if expansion_rows else ("cold" if cold_front_rows else None),
        }

    def _log_front_diagnostics(self, ctx: AIContext, plan: StrategicPlan):
        key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
            ctx.side,
        )
        if key in self._front_diag_logged_phase:
            return
        self._front_diag_logged_phase.add(key)

        front_analysis = ctx.front_analysis or self._build_front_analysis(ctx, plan)
        expansion_rows = list(front_analysis.get("expansion", []) or [])
        cold_rows = list(front_analysis.get("cold", []) or [])

        def fmt(rows: List[Dict[str, Any]]) -> str:
            if not rows:
                return "-"
            return ",".join(
                f"{r.get('country_id')}:f{int(r.get('frontier_count', 0) or 0)}:"
                f"d{int(r.get('min_dist', 999) or 999)}:s{float(r.get('score', 0.0) or 0.0):.0f}"
                for r in rows[:3]
            )

        amphib = "-"
        if plan.transport_campaign or plan.beachhead_slots:
            slots = [h.axial_to_offset() for h in (plan.beachhead_slots or [])]
            amphib = f"slots={slots[:4]} embarked={len(ctx.embarked_ground)}"

        main_id = getattr(plan.main_objective, "id", None) if plan.main_objective else None
        debug_print(
            f"[FRONT] side={ctx.side} posture={plan.posture} main={main_id} "
            f"hot={int(front_analysis.get('hot_count', 0) or 0)} "
            f"enemy_pressure={int(front_analysis.get('enemy_pressure_count', 0) or 0)} "
            f"primary={front_analysis.get('primary_mode')}:{front_analysis.get('primary_country_id')} "
            f"expansion={fmt(expansion_rows)} cold={fmt(cold_rows)} amphibious={amphib}"
        )

    def _current_scenario_id(self) -> str:
        return str(getattr(getattr(self.game_state, "scenario_spec", None), "id", "") or "")

    def _ensure_static_geo_cache(self):
        scenario_id = self._current_scenario_id()
        if self._static_geo_cache_scenario_id == scenario_id and self._country_hexes_by_id_cache is not None:
            return
        board = self.game_state.map
        country_hexes: Dict[str, List[Hex]] = defaultdict(list)
        country_id_by_offset: Dict[Tuple[int, int], str] = {}
        for country in self.game_state.countries.values():
            cid = str(getattr(country, "id", "") or "")
            if not cid:
                continue
            for col, row in list(getattr(country, "territories", []) or []):
                country_hexes[cid].append(Hex.offset_to_axial(col, row))
                country_id_by_offset[(int(col), int(row))] = cid

        coastal_hexes: List[Hex] = []
        for col in range(int(getattr(board, "width", 0) or 0)):
            for row in range(int(getattr(board, "height", 0) or 0)):
                h = Hex.offset_to_axial(col, row)
                if board.is_coastal(h):
                    coastal_hexes.append(h)
        port_counts: Dict[str, int] = {}
        for cid, country in self.game_state.countries.items():
            port_counts[cid] = sum(
                1 for loc in country.locations.values()
                if getattr(loc, "loc_type", None) == LocType.PORT.value
            )
        self._static_geo_cache_scenario_id = scenario_id
        self._country_hexes_by_id_cache = dict(country_hexes)
        self._country_port_counts_cache = dict(port_counts)
        self._coastal_hexes_cache = list(coastal_hexes)
        self._country_id_by_offset_cache = dict(country_id_by_offset)

    def _get_country_hexes_by_id(self) -> Dict[str, List[Hex]]:
        self._ensure_static_geo_cache()
        return self._country_hexes_by_id_cache or {}

    def _get_country_port_counts(self) -> Dict[str, int]:
        self._ensure_static_geo_cache()
        return self._country_port_counts_cache or {}

    def _get_coastal_hexes(self) -> List[Hex]:
        self._ensure_static_geo_cache()
        return self._coastal_hexes_cache or []

    def _get_country_id_by_offset(self) -> Dict[Tuple[int, int], str]:
        self._ensure_static_geo_cache()
        return self._country_id_by_offset_cache or {}

    def _get_neutral_front_cache(self, side: str) -> Dict[str, Any]:
        phase_key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
            side,
        )
        cache = self._neutral_front_cache_by_side.get(side)
        if cache and cache.get("phase_key") == phase_key:
            return cache
        cache = {
            "phase_key": phase_key,
            "invasion_target": None,
            "staging_hexes": None,
        }
        self._neutral_front_cache_by_side[side] = cache
        return cache

    def _ensure_movement_phase_memory(self) -> set:
        key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._movement_phase_key != key:
            self._movement_phase_key = key
            self._moved_task_groups_in_phase = set()
            self._movement_phase_plan_cache_by_side = {}
            self._neutral_front_cache_by_side = {}
            self._front_diag_logged_phase = set()
        return self._moved_task_groups_in_phase

    def _ensure_transport_phase_memory(self) -> set:
        key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._transport_phase_key != key:
            self._transport_phase_key = key
            self._transport_actions_in_phase = set()
            for side, state in self._invasion_state_by_side.items():
                for uk in state.get("landed_armies", set()) or set():
                    self._transport_actions_in_phase.add(("landed_army", uk))
                for uk in state.get("landed_leaders", set()) or set():
                    self._transport_actions_in_phase.add(("landed_leader", uk))
        return self._transport_actions_in_phase

    def _compute_transport_signature(self, ctx: AIContext) -> Tuple[Tuple[Any, ...], ...]:
        """
        Compute a signature of the current transport state, to determine if cached transport plans are still valid.
        This includes the positions of all fleets, and the count of embarked ground units in each fleet, since that
        affects disembarkation possibilities.
        """
        rows: List[Tuple[Any, ...]] = []
        for u in sorted(ctx.friendly_units, key=_unit_key):
            if not u.is_fleet():
                continue
            if not u.is_on_map:
                continue
            pos = tuple(getattr(u, "position", (None, None)) or (None, None))
            embarked_ground = sum(
                1 for p in list(getattr(u, "passengers", []) or [])
                if p.allegiance == ctx.side
                and p.is_army()
            )
            rows.append((_unit_key(u), pos, embarked_ground))
        return tuple(rows)

    def _cached_slots_still_valid(self, ctx: AIContext, cache: Dict[str, Any]) -> bool:
        """
        Check if cached beachhead landing slots are still valid.
        If no slots cached, consider valid (may be waiting on slot generation).
        """
        slots = list(cache.get("beachhead_slots", []) or [])
        if not slots:
            return True
        board = self.game_state.map
        for item in slots:
            try:
                col, row = int(item[0]), int(item[1])
                h = Hex.offset_to_axial(col, row)
            except Exception:
                continue
            if not self.game_state.is_hex_in_bounds(col, row):
                continue
            if not board.is_coastal(h):
                continue
            if not ctx.embarked_ground:
                return True
            if any(self.movement_service.can_unboard_unit_to_hex(p, h) for p in ctx.embarked_ground):
                return True
        return False

    def _collect_objectives(self, side: str, objective_graph: Optional[Dict[str, Any]] = None) -> List[Objective]:
        objective_graph = objective_graph or {}
        location_targets = set(objective_graph.get("offensive_target_locations", set()) or set())
        country_targets = set(objective_graph.get("offensive_target_countries", set()) or set())
        defend_location_targets = set(objective_graph.get("defensive_target_locations", set()) or set())
        defend_country_targets = set(objective_graph.get("defensive_target_countries", set()) or set())
        enemy_offensive_countries = set(objective_graph.get("enemy_offensive_countries", set()) or set())
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
                if loc.id in defend_location_targets:
                    value += 18
                if country.id in defend_country_targets:
                    value += 16
                if country.id in enemy_offensive_countries and loc.loc_type == LocType.PORT.value:
                    value += 20
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

    def _get_invasion_state(self, side: str) -> Dict[str, Any]:
        if side not in self._invasion_state_by_side:
            self._invasion_state_by_side[side] = {
                "objective_country_ids": set(),
                "objective_location_ids": set(),
                "primary_objective_id": None,
                "anchor_hex": None,
                "landing_slots": [],
                "fleet_assignments": {},
                "landed_armies": set(),
                "landed_leaders": set(),
                "ashore_committed_armies": set(),
                "committed_fleets": set(),
                "version": 1,
            }
        return self._invasion_state_by_side[side]

    def _update_invasion_state_from_plan(self, side: str, plan: StrategicPlan):
        state = self._get_invasion_state(side)
        old_anchor = state.get("anchor_hex")
        old_slots = list(state.get("landing_slots", []) or [])
        state["primary_objective_id"] = getattr(plan.main_objective, "id", None) if plan.main_objective else None
        state["objective_country_ids"] = set(
            o.country_id for o in (plan.objectives or []) if getattr(o, "country_id", None) and o.owner != side
        )
        state["objective_location_ids"] = set(o.id for o in (plan.objectives or []) if o.owner != side)
        if plan.beachhead_hex is not None:
            state["anchor_hex"] = plan.beachhead_hex.axial_to_offset()
        state["landing_slots"] = [h.axial_to_offset() for h in (plan.beachhead_slots or [])]
        if old_anchor != state.get("anchor_hex") or old_slots != state.get("landing_slots", []):
            state["version"] = int(state.get("version", 0) or 0) + 1
        if plan.fleet_slot_assignments:
            state["fleet_assignments"] = dict(plan.fleet_slot_assignments)

    def _clear_ashore_committed_flag_if_explicitly_retasked(self, side: str, unit):
        # Conservative by default: only clear if unit is no longer a valid on-map friendly ground army.
        if unit is None:
            return
        if not unit.is_army():
            return
        state = self._get_invasion_state(side)
        key = _unit_key(unit)
        if key not in state.get("ashore_committed_armies", set()):
            return
        if unit.allegiance != side or not unit.is_on_map:
            state["ashore_committed_armies"].discard(key)

    def _prune_ashore_committed_state(self, side: str):
        state = self._get_invasion_state(side)
        committed = set(state.get("ashore_committed_armies", set()) or set())
        if not committed:
            return
        valid = {
            _unit_key(u)
            for u in self.game_state.units
            if u.allegiance == side
            and u.is_on_map
            and u.is_army()
        }
        state["ashore_committed_armies"] = committed.intersection(valid)

    def _clear_landed_flag_if_inland(self, side: str, unit):
        if not (unit.is_army() or unit.is_leader()):
            return
        if not unit.position or None in unit.position:
            return
        state = self._get_invasion_state(side)
        key = _unit_key(unit)
        landed_key = "landed_armies" if unit.is_army() else "landed_leaders"
        if key not in state.get(landed_key, set()):
            return
        unit_hex = Hex.offset_to_axial(*unit.position)
        landing_slots = [Hex.offset_to_axial(int(c), int(r)) for (c, r) in state.get("landing_slots", []) or []]
        if (not self.game_state.map.is_coastal(unit_hex)) or all(unit_hex.distance_to(h) > 1 for h in landing_slots):
            state[landed_key].discard(key)

    def _log(self, msg: str):
        debug_print(f"AI[{self.game_state.active_player}] {msg}")
