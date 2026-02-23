from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from src.content.constants import HL, WS
from src.content.specs import UnitState, UnitType
from src.game.map import Hex


def _slugify(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


@dataclass
class VictoryStatus:
    game_over: bool = False
    winner: str | None = None
    reason: str = ""
    major_winner: str | None = None
    major_reason: str = ""
    minor_points: Dict[str, int] = field(default_factory=lambda: {HL: 0, WS: 0})


class VictoryConditionEvaluator:
    """Structured victory evaluator (no legacy string parsing)."""

    def __init__(self, game_state):
        self.game_state = game_state
        self._normalized = {
            HL: self._normalize_side_victory(self._side_victory_raw(HL)),
            WS: self._normalize_side_victory(self._side_victory_raw(WS)),
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

    def _normalize_side_victory(self, raw_side: Any) -> Dict[str, Any]:
        if not isinstance(raw_side, dict):
            return {}

        normalized = {}
        major = raw_side.get("major")
        if major is not None:
            normalized["major"] = self._normalize_node(major)

        minor = raw_side.get("minor")
        if minor is None and "marginal" in raw_side:
            minor = raw_side.get("marginal")
        normalized["minor"] = self._normalize_minor(minor)
        return normalized

    def _normalize_minor(self, minor_raw: Any) -> Dict[str, Any]:
        if minor_raw is None:
            return {"points_to_win": 1, "conditions": []}

        if isinstance(minor_raw, dict) and "conditions" in minor_raw:
            points_to_win = int(minor_raw.get("points_to_win", 1) or 1)
            conditions = []
            for item in minor_raw.get("conditions", []) or []:
                if isinstance(item, dict) and "when" in item:
                    points = int(item.get("points", 1) or 1)
                    node = self._normalize_node(item.get("when"))
                else:
                    points = 1
                    node = self._normalize_node(item)
                conditions.append({"points": points, "node": node})
            return {"points_to_win": points_to_win, "conditions": conditions}

        if isinstance(minor_raw, list):
            conditions = [{"points": 1, "node": self._normalize_node(item)} for item in minor_raw]
            return {"points_to_win": max(1, len(conditions)), "conditions": conditions}

        node = self._normalize_node(minor_raw)
        return {"points_to_win": 1, "conditions": [{"points": 1, "node": node}]}

    def _normalize_node(self, node: Any) -> Dict[str, Any]:
        end_turn = int(getattr(self.game_state.scenario_spec, "end_turn", 30) or 30)

        if isinstance(node, dict):
            if "all" in node:
                out = {
                    "all": [self._normalize_node(child) for child in node.get("all", []) or []]
                }
                if "by_turn" in node:
                    out["by_turn"] = int(node["by_turn"])
                return out
            if "any" in node:
                out = {
                    "any": [self._normalize_node(child) for child in node.get("any", []) or []]
                }
                if "by_turn" in node:
                    out["by_turn"] = int(node["by_turn"])
                return out
            out = dict(node)
            if "by_turn" not in out:
                out["by_turn"] = end_turn
            return out

        # Legacy strings were intentionally removed.
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

    def _is_node_satisfied(self, node: Dict[str, Any], side: str, turn: int) -> bool:
        deadline = int(node.get("by_turn", getattr(self.game_state.scenario_spec, "end_turn", 30)))

        # Generic cutoff: after deadline it cannot be newly satisfied.
        if turn > deadline:
            return False

        if "all" in node:
            return all(self._is_node_satisfied(child, side, turn) for child in node.get("all", []))

        if "any" in node:
            return any(self._is_node_satisfied(child, side, turn) for child in node.get("any", []))

        node_type = str(node.get("type", "unknown"))

        # Deadline-checkpoint conditions must only be decided at/after deadline.
        if self._requires_deadline_checkpoint(node_type) and turn < deadline:
            return False

        return self._evaluate_leaf(node, side)

    @staticmethod
    def _requires_deadline_checkpoint(node_type: str) -> bool:
        return node_type in {
            "prevent_country_conquered",
            "prevent_location_captured",
            "prevent_country_control",
            "survive_unit_score",
            "escape_unit_score",
        }

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
                if self._is_country_controlled_by_side(c, side)
            )
            return controlled >= required

        if node_type == "prevent_country_control":
            country = self.game_state.countries.get(_slugify(node.get("country", "")))
            enemy = node.get("enemy") or self.game_state.get_enemy_allegiance(side)
            return bool(country and country.allegiance != enemy)

        if node_type == "destroy_unit_score":
            return self._score_units(mode="destroy", side=side, node=node) >= int(node.get("min_points", 0) or 0)

        if node_type == "survive_unit_score":
            return self._score_units(mode="survive", side=side, node=node) >= int(node.get("min_points", 0) or 0)

        if node_type == "escape_unit_score":
            return self._score_units(mode="escape", side=side, node=node) >= int(node.get("min_points", 0) or 0)

        return False

    def _score_units(self, mode: str, side: str, node: Dict[str, Any]) -> int:
        candidates = list(self._iter_scored_units(mode, side, node))
        score = 0

        for unit in candidates:
            status = getattr(unit, "status", None)
            if mode == "destroy":
                if status == UnitState.DESTROYED:
                    score += 2
                elif status == UnitState.DEPLETED:
                    score += 1
            elif mode in ("survive", "escape"):
                if status == UnitState.ACTIVE:
                    score += 2
                elif status == UnitState.DEPLETED:
                    score += 1

        return score

    def _iter_scored_units(self, mode: str, side: str, node: Dict[str, Any]) -> Iterable[Any]:
        if mode == "destroy":
            allegiance = self.game_state.get_enemy_allegiance(side)
        else:
            allegiance = side

        unit_filter = self._normalize_unit_types(node.get("unit_types", "units"))
        country_filter = _slugify(node.get("country", "")) if node.get("country") else None
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != allegiance:
                continue
            if not self._matches_country_or_dragonflight(unit, country_filter):
                continue
            if not self._matches_unit_types(unit, unit_filter):
                continue
            if mode == "escape" and not bool(getattr(unit, "escaped", False)):
                continue
            yield unit

    @staticmethod
    def _normalize_hexes(values: Any) -> set[Tuple[int, int]]:
        out = set()
        if not isinstance(values, list):
            return out
        for item in values:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                try:
                    out.add((int(item[0]), int(item[1])))
                except Exception:
                    continue
        return out

    @staticmethod
    def _normalize_unit_types(value: Any) -> set[str]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, list):
            items = value
        else:
            items = ["units"]

        normalized = set()
        for v in items:
            low = str(v).strip().lower()
            if low in {"units", "unit"}:
                normalized.add("units")
            elif low in {"fleet", "fleets", "ship", "ships"}:
                normalized.add("fleets")
            elif low in {"leader", "leaders"}:
                normalized.add("leaders")

        if not normalized:
            normalized.add("units")
        return normalized

    def _matches_unit_types(self, unit: Any, unit_filter: set[str]) -> bool:
        if "units" in unit_filter:
            is_army = hasattr(unit, "is_army") and unit.is_army()
            is_wing = getattr(unit, "unit_type", None) == UnitType.WING
            is_fleet = getattr(unit, "unit_type", None) == UnitType.FLEET
            if is_army or is_wing or is_fleet:
                return True

        if "fleets" in unit_filter and getattr(unit, "unit_type", None) == UnitType.FLEET:
            return True

        if "leaders" in unit_filter and hasattr(unit, "is_leader") and unit.is_leader():
            return True

        return False

    @staticmethod
    def _matches_country_or_dragonflight(unit: Any, country_filter: str | None) -> bool:
        if not country_filter:
            return True
        unit_country = _slugify(getattr(unit, "land", "") or "")
        unit_df = _slugify(getattr(getattr(unit, "spec", None), "dragonflight", "") or "")
        return country_filter in {unit_country, unit_df}

    def get_escape_rules_for_side(self, side: str, turn: int | None = None) -> List[Dict[str, Any]]:
        """
        Returns normalized escape rules from major/minor trees for a side.
        Used by movement flow to mark eligible units as escaped immediately.
        """
        current_turn = int(getattr(self.game_state, "turn", 0) if turn is None else turn)
        collected: List[Dict[str, Any]] = []
        side_block = self._normalized.get(side, {}) or {}

        major = side_block.get("major")
        if major:
            self._collect_escape_rules(major, current_turn, collected)

        minor = side_block.get("minor", {}) or {}
        for item in minor.get("conditions", []) or []:
            node = item.get("node")
            if node:
                self._collect_escape_rules(node, current_turn, collected)
        return collected

    def _collect_escape_rules(self, node: Dict[str, Any], turn: int, out: List[Dict[str, Any]]):
        deadline = int(node.get("by_turn", getattr(self.game_state.scenario_spec, "end_turn", 30)))
        if turn > deadline:
            return

        if "all" in node:
            for child in node.get("all", []) or []:
                self._collect_escape_rules(child, turn, out)
            return

        if "any" in node:
            for child in node.get("any", []) or []:
                self._collect_escape_rules(child, turn, out)
            return

        if str(node.get("type", "")) != "escape_unit_score":
            return

        out.append(
            {
                "country_filter": _slugify(node.get("country", "")) if node.get("country") else None,
                "unit_filter": self._normalize_unit_types(node.get("unit_types", "units")),
                "hexes": self._normalize_hexes(node.get("hexes") or node.get("escape_hexes") or []),
            }
        )

    def unit_matches_escape_rule(self, unit: Any, target_offset: Tuple[int, int], rule: Dict[str, Any], side: str) -> bool:
        if getattr(unit, "allegiance", None) != side:
            return False
        if bool(getattr(unit, "escaped", False)):
            return False
        if tuple(target_offset) not in (rule.get("hexes") or set()):
            return False
        if not self._matches_country_or_dragonflight(unit, rule.get("country_filter")):
            return False
        if not self._matches_unit_types(unit, rule.get("unit_filter") or {"units"}):
            return False
        return True

    def _is_location_controlled_by(self, location_id: str, allegiance: str) -> bool:
        if allegiance not in (HL, WS):
            return False
        if not location_id:
            return False

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

    @staticmethod
    def _is_country_controlled_by_side(country: Any, side: str) -> bool:
        """
        Control includes:
        - Allied unconquered countries (country.allegiance == side and not conquered)
        - Enemy-origin conquered countries where all locations are occupied by side
        """
        if getattr(country, "allegiance", None) == side and not bool(getattr(country, "conquered", False)):
            return True

        if not bool(getattr(country, "conquered", False)):
            return False

        locations = list(getattr(country, "locations", {}).values())
        if not locations:
            return False
        return all(getattr(loc, "occupier", None) == side for loc in locations)
