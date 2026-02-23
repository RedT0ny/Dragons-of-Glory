import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.content.constants import HL, WS


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def _split_country_list(raw: str) -> List[str]:
    text = raw.replace(".", " ")
    text = re.sub(r"\band\b", ",", text, flags=re.IGNORECASE)
    parts = [p.strip() for p in text.split(",")]
    return [_slugify(p) for p in parts if p.strip()]


def _extract_deadline(text: str, default_turn: int):
    t = str(text).strip()
    match = re.search(r"\bby(?:\s+end\s+of)?\s+turn\s+(\d+)\b", t, flags=re.IGNORECASE)
    if match:
        deadline = int(match.group(1))
        t = (t[: match.start()] + t[match.end() :]).strip()
        t = re.sub(r"\s+", " ", t)
        return t, deadline
    return t, default_turn


def _parse_legacy_atom(atom: str, side: str, default_turn: int) -> Dict[str, Any]:
    raw_atom = atom.strip().rstrip(".")
    atom_text, deadline = _extract_deadline(raw_atom, default_turn)
    low = atom_text.lower().strip()

    m = re.match(r"^conquer\s+(.+)$", low)
    if m:
        return {"type": "conquer_country", "country": _slugify(m.group(1)), "by_turn": deadline}

    m = re.match(r"^capture\s+(.+)$", low)
    if m:
        return {"type": "capture_location", "location": _slugify(m.group(1)), "by_turn": deadline}

    m = re.match(r"^prevent\s+(.+)\s+from\s+being\s+conquered$", low)
    if m:
        return {"type": "prevent_country_conquered", "country": _slugify(m.group(1)), "by_turn": deadline}

    m = re.match(r"^prevent\s+(.+)\s+from\s+being\s+captured$", low)
    if m:
        return {"type": "prevent_location_captured", "location": _slugify(m.group(1)), "by_turn": deadline}

    m = re.match(r"^ally\s+(.+)$", low)
    if m:
        return {"type": "ally_country", "country": _slugify(m.group(1)), "by_turn": deadline}

    m = re.match(r"^control\s+(\d+)\s+countries$", low)
    if m:
        return {"type": "control_n_countries", "count": int(m.group(1)), "by_turn": deadline}

    m = re.match(r"^control\s+(.+)$", low)
    if m:
        countries = _split_country_list(m.group(1))
        return {
            "all": [{"type": "ally_country", "country": c, "by_turn": deadline} for c in countries]
        }

    m = re.match(r"^prevent\s+(hl|highlord|ws|whitestone)\s+from\s+controlling\s+(.+)$", low)
    if m:
        enemy_key = m.group(1)
        enemy = HL if enemy_key in ("hl", "highlord") else WS
        countries = _split_country_list(m.group(2))
        return {
            "all": [
                {
                    "type": "prevent_country_control",
                    "country": c,
                    "enemy": enemy,
                    "by_turn": deadline,
                }
                for c in countries
            ]
        }

    return {"type": "unknown", "raw": raw_atom, "by_turn": deadline}


def parse_legacy_expression(text: str, side: str, default_turn: int) -> Dict[str, Any]:
    expr_text, deadline = _extract_deadline(text, default_turn)
    or_terms = [t.strip() for t in re.split(r"\bor\b", expr_text, flags=re.IGNORECASE) if t.strip()]
    if len(or_terms) > 1:
        return {
            "any": [parse_legacy_expression(t, side, deadline) for t in or_terms],
            "by_turn": deadline,
        }

    direct = _parse_legacy_atom(expr_text, side, deadline)
    if direct.get("type") != "unknown":
        return direct

    and_terms = [t.strip() for t in re.split(r"\band\b", expr_text, flags=re.IGNORECASE) if t.strip()]
    if len(and_terms) > 1:
        return {
            "all": [_parse_legacy_atom(t, side, deadline) for t in and_terms],
            "by_turn": deadline,
        }

    return direct


@dataclass
class VictoryStatus:
    game_over: bool = False
    winner: str | None = None
    reason: str = ""
    major_winner: str | None = None
    major_reason: str = ""
    minor_points: Dict[str, int] = field(default_factory=lambda: {HL: 0, WS: 0})


class VictoryConditionEvaluator:
    def __init__(self, game_state):
        self.game_state = game_state
        self._achieved = {HL: set(), WS: set()}
        self._normalized = {
            HL: self._normalize_side_victory(self._side_victory_raw(HL), HL),
            WS: self._normalize_side_victory(self._side_victory_raw(WS), WS),
        }

    def evaluate(self) -> VictoryStatus:
        turn = int(getattr(self.game_state, "turn", 0) or 0)
        end_turn = int(getattr(self.game_state.scenario_spec, "end_turn", 0) or 0)
        status = VictoryStatus()

        for side in (HL, WS):
            side_block = self._normalized.get(side, {})
            major_root = side_block.get("major")
            if major_root and self._is_node_satisfied(major_root, side, turn):
                status.major_winner = side
                status.major_reason = "major_condition"
                status.game_over = True
                status.winner = side
                status.reason = "major_victory"
                return status

        for side in (HL, WS):
            status.minor_points[side] = self._compute_minor_points(side, turn)

        if turn >= end_turn > 0:
            hl_points = status.minor_points.get(HL, 0)
            ws_points = status.minor_points.get(WS, 0)
            if hl_points > ws_points:
                status.game_over = True
                status.winner = HL
                status.reason = "minor_points"
            elif ws_points > hl_points:
                status.game_over = True
                status.winner = WS
                status.reason = "minor_points"
            else:
                status.game_over = True
                status.winner = None
                status.reason = "draw"

        return status

    def _side_victory_raw(self, side: str) -> Any:
        vc = getattr(self.game_state.scenario_spec, "victory_conditions", {}) or {}
        return vc.get(side, {})

    def _normalize_side_victory(self, raw_side: Any, side: str) -> Dict[str, Any]:
        end_turn = int(getattr(self.game_state.scenario_spec, "end_turn", 30) or 30)
        if not isinstance(raw_side, dict):
            return {}

        normalized = {}
        major = raw_side.get("major")
        if major is not None:
            normalized["major"] = self._normalize_node(major, side, end_turn)

        minor = raw_side.get("minor")
        if minor is None and "marginal" in raw_side:
            minor = raw_side.get("marginal")
        normalized["minor"] = self._normalize_minor(minor, side, end_turn)
        return normalized

    def _normalize_minor(self, minor_raw: Any, side: str, end_turn: int) -> Dict[str, Any]:
        if minor_raw is None:
            return {"points_to_win": 1, "conditions": []}

        if isinstance(minor_raw, dict) and "conditions" in minor_raw:
            points_to_win = int(minor_raw.get("points_to_win", 1) or 1)
            conditions = []
            for item in minor_raw.get("conditions", []) or []:
                if isinstance(item, dict) and "when" in item:
                    points = int(item.get("points", 1) or 1)
                    node = self._normalize_node(item.get("when"), side, end_turn)
                else:
                    points = 1
                    node = self._normalize_node(item, side, end_turn)
                conditions.append({"points": points, "node": node})
            return {"points_to_win": points_to_win, "conditions": conditions}

        if isinstance(minor_raw, list):
            conditions = [{"points": 1, "node": self._normalize_node(item, side, end_turn)} for item in minor_raw]
            return {"points_to_win": max(1, len(conditions)), "conditions": conditions}

        node = self._normalize_node(minor_raw, side, end_turn)
        return {"points_to_win": 1, "conditions": [{"points": 1, "node": node}]}

    def _normalize_node(self, node: Any, side: str, end_turn: int) -> Dict[str, Any]:
        if isinstance(node, str):
            return parse_legacy_expression(node, side, end_turn)
        if isinstance(node, dict):
            if "all" in node:
                out = {
                    "all": [self._normalize_node(child, side, end_turn) for child in node.get("all", []) or []]
                }
                if "by_turn" in node:
                    out["by_turn"] = int(node["by_turn"])
                return out
            if "any" in node:
                out = {
                    "any": [self._normalize_node(child, side, end_turn) for child in node.get("any", []) or []]
                }
                if "by_turn" in node:
                    out["by_turn"] = int(node["by_turn"])
                return out
            out = dict(node)
            if "by_turn" not in out:
                out["by_turn"] = end_turn
            return out
        return {"type": "unknown", "raw": str(node), "by_turn": end_turn}

    def _compute_minor_points(self, side: str, turn: int) -> int:
        block = self._normalized.get(side, {})
        minor = block.get("minor", {}) or {}
        total = 0
        for item in minor.get("conditions", []):
            node = item.get("node")
            points = int(item.get("points", 1) or 1)
            if node and self._is_node_satisfied(node, side, turn):
                total += points
        return total

    def _node_key(self, node: Dict[str, Any]) -> str:
        if "all" in node:
            return "all(" + ",".join(self._node_key(c) for c in node.get("all", [])) + f")@{node.get('by_turn','')}"
        if "any" in node:
            return "any(" + ",".join(self._node_key(c) for c in node.get("any", [])) + f")@{node.get('by_turn','')}"
        parts = [str(node.get("type", "unknown"))]
        for k in sorted(k for k in node.keys() if k != "type"):
            parts.append(f"{k}={node[k]}")
        return "|".join(parts)

    def _is_node_satisfied(self, node: Dict[str, Any], side: str, turn: int) -> bool:
        key = self._node_key(node)
        if key in self._achieved[side]:
            return True

        deadline = int(node.get("by_turn", getattr(self.game_state.scenario_spec, "end_turn", 30)))
        if turn > deadline:
            return False

        if "all" in node:
            ok = all(self._is_node_satisfied(child, side, turn) for child in node.get("all", []))
            if ok:
                self._achieved[side].add(key)
            return ok

        if "any" in node:
            ok = any(self._is_node_satisfied(child, side, turn) for child in node.get("any", []))
            if ok:
                self._achieved[side].add(key)
            return ok

        ok = self._evaluate_leaf(node, side)
        if ok:
            self._achieved[side].add(key)
        return ok

    def _evaluate_leaf(self, node: Dict[str, Any], side: str) -> bool:
        node_type = str(node.get("type", "unknown"))
        if node_type == "conquer_country":
            country = self.game_state.countries.get(_slugify(node.get("country", "")))
            return bool(country and country.conquered)

        if node_type == "capture_location":
            loc_id = _slugify(node.get("location", ""))
            return self._is_location_controlled_by(loc_id, side)

        if node_type == "prevent_country_conquered":
            country = self.game_state.countries.get(_slugify(node.get("country", "")))
            return bool(country and not country.conquered)

        if node_type == "prevent_location_captured":
            loc_id = _slugify(node.get("location", ""))
            enemy = self.game_state.get_enemy_allegiance(side)
            return not self._is_location_controlled_by(loc_id, enemy)

        if node_type == "ally_country":
            country = self.game_state.countries.get(_slugify(node.get("country", "")))
            return bool(country and country.allegiance == side)

        if node_type == "control_n_countries":
            required = int(node.get("count", 0) or 0)
            controlled = sum(
                1
                for c in self.game_state.countries.values()
                if c.allegiance == side and not c.conquered
            )
            return controlled >= required

        if node_type == "prevent_country_control":
            country = self.game_state.countries.get(_slugify(node.get("country", "")))
            enemy = node.get("enemy") or self.game_state.get_enemy_allegiance(side)
            return bool(country and country.allegiance != enemy)

        if node_type == "unknown":
            return False

        return False

    def _is_location_controlled_by(self, location_id: str, allegiance: str) -> bool:
        if allegiance not in (HL, WS):
            return False
        if not location_id:
            return False
        from src.game.map import Hex

        for country in self.game_state.countries.values():
            loc = country.locations.get(location_id)
            if not loc or not loc.coords:
                continue
            hex_obj = Hex.offset_to_axial(*loc.coords)
            units = self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
            for unit in units:
                if not getattr(unit, "is_on_map", False):
                    continue
                if unit.allegiance != allegiance:
                    continue
                if hasattr(unit, "is_army") and unit.is_army():
                    return True
            return False
        return False
