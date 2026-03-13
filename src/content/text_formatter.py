from typing import Any, Iterable
from src.content.specs import UnitType


def to_roman(n: int):
    """Convert an integer to Roman numeral."""
    if not n: return ""
    roman_map = [(10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    result = ""
    for value, symbol in roman_map:
        while n >= value:
            result += symbol
            n -= value
    return result


def caption_id(unit_id: str):
    """Transform a unit ID string according to the specified rules.

    Example: 'kern_ogre_inf_1' → '1 Kern'
    Example: 'solamnia' → 'Solamnia'

    Args:
        unit_id: The original unit ID string

    Returns:
        Transformed string according to the rules
    """
    id_text = f"{unit_id}"

    if '_' in id_text:
        parts = id_text.split('_')
        if parts[-1].isdigit():
            if parts[0] == 'dtemple':
                # If it's a Draconian
                return f"{to_roman(int(parts[-1]))} {parts[1].capitalize()}"
            elif parts[0] == 'taman':
                return f"{to_roman(int(parts[-1]))} Neraka"
            elif parts[0] == 'nergoth':
                return f"{to_roman(int(parts[-1]))} N.Ergoth"
            return f"{to_roman(int(parts[-1]))} {parts[0].capitalize()}"
        elif len(parts) > 2:
            # If more than 2 parts and no number at end, return first part capitalized
            return parts[0].capitalize()
        # If underscores but parts[-1] is not a digit, return first letter of parts[0]
        # capitalized and followed by a dot, a space, and parts[1] capitalized
        return f"{parts[0][0].capitalize()}. {parts[1].capitalize()}"

    # No underscores: capitalize the whole thing
    return id_text.capitalize()


class TextFormatter:
    """
    Formats structured gameplay text for UI consumption, backed by Translator data.
    """

    def __init__(self, translator):
        self.translator = translator
        self._tdata = getattr(translator, "translations", {}) or {}

    @staticmethod
    def format_units(units: Iterable[object]) -> str:
        return ", ".join(TextFormatter.format_unit_log_string(u) for u in units) if units else "-"

    @staticmethod
    def format_combat_log(attackers, defenders, result):
        attacker_names = TextFormatter.format_units(attackers)
        defender_names = TextFormatter.format_units(defenders)
        return f"Combat result {result}: Attackers [{attacker_names}] vs Defenders [{defender_names}]"

    @staticmethod
    def format_naval_log(attackers, defenders, outcome):
        attacker_names = ", ".join(TextFormatter.format_unit_log_string(u) for u in attackers if u.is_fleet())
        defender_names = ", ".join(TextFormatter.format_unit_log_string(u) for u in defenders if u.is_fleet())
        rounds = outcome.get("rounds", 0)
        result = outcome.get("result", "-/-")
        return f"Naval combat {result} after {rounds} rounds: Attackers [{attacker_names}] vs Defenders [{defender_names}]"

    @staticmethod
    def format_unit_log_string(unit):
        ordinal = getattr(unit, "ordinal", None)
        id_text = getattr(unit, "id", "Unknown")

        if '_' in id_text:
            parts = id_text.split('_')

            if ordinal:
                # If more than 2 parts and no number at end, return first part capitalized
                return f"{to_roman(ordinal)} {' '.join(p.capitalize() for p in parts[0:3])}"
            # If underscores but no ordinal, return the capitalized name
            return " ".join(p.capitalize() for p in parts[0:])

        # No underscores: capitalize the whole thing
        return id_text.capitalize()

    @staticmethod
    def format_target_hex(target_hex) -> str:
        if target_hex is None:
            return "-"
        if hasattr(target_hex, "axial_to_offset"):
            col, row = target_hex.axial_to_offset()
            return f"({col}, {row})"
        if isinstance(target_hex, (tuple, list)) and len(target_hex) == 2:
            return f"({target_hex[0]}, {target_hex[1]})"
        return str(target_hex)

    def format_victory_conditions(self, victory_block: dict[str, Any] | None) -> str:
        if not isinstance(victory_block, dict):
            return ""

        lines = []
        major = victory_block.get("major")
        if major is not None:
            major_label = self._tr("victory.labels.major", "Major")
            lines.append(f"{major_label}: {self._format_node(major)}")

        minor = victory_block.get("minor")
        if minor is None and "marginal" in victory_block:
            minor = victory_block.get("marginal")
        if minor is not None:
            minor_label = self._tr("victory.labels.minor", "Minor")
            lines.extend(self._format_minor(minor_label, minor))

        return "\n".join(line for line in lines if line).strip()

    def _format_minor(self, minor_label: str, minor: Any) -> list[str]:
        if not isinstance(minor, dict) or "conditions" not in minor:
            return [f"{minor_label}: {self._format_node(minor)}"]

        lines = [f"{minor_label}:"]
        points_to_win = minor.get("points_to_win")
        if points_to_win is not None:
            target_label = self._tr("victory.labels.points_to_win", "Points to win")
            lines.append(f"{target_label}: {points_to_win}")

        for item in minor.get("conditions", []) or []:
            if isinstance(item, dict) and "when" in item:
                points = int(item.get("points", 1) or 1)
                point_word = self._tr("victory.labels.points", "points")
                lines.append(f"+{points} {point_word}: {self._format_node(item.get('when'))}")
            else:
                lines.append(f"+1 {self._tr('victory.labels.points', 'points')}: {self._format_node(item)}")
        return lines

    def _format_node(self, node: Any) -> str:
        if isinstance(node, dict):
            if "all" in node:
                return self._join_group(node.get("all", []), op_key="all")
            if "any" in node:
                return self._join_group(node.get("any", []), op_key="any")
            return self._format_leaf(node)
        if isinstance(node, list):
            return self._join_group(node, op_key="all")
        return str(node)

    def _join_group(self, nodes: list[Any], op_key: str) -> str:
        pieces = [self._format_node(n) for n in nodes if n is not None]
        pieces = [p for p in pieces if p]
        if not pieces:
            return ""
        if len(pieces) == 1:
            return pieces[0]
        op = self._tr(f"victory.operators.{op_key}", "and" if op_key == "all" else "or")
        return f"({f' {op} '.join(pieces)})"

    def _format_leaf(self, node: dict[str, Any]) -> str:
        node_type = str(node.get("type", "unknown"))
        by_turn = node.get("by_turn")

        if node_type == "conquer_country":
            text = self._tr("victory.types.conquer_country", "Conquer {country}").format(
                country=self._country_name(node.get("country"))
            )
            return self._with_deadline(text, by_turn)

        if node_type == "capture_location":
            text = self._tr("victory.types.capture_location", "Capture {location}").format(
                location=self._location_name(node.get("location"))
            )
            return self._with_deadline(text, by_turn)

        if node_type == "prevent_country_conquered":
            text = self._tr(
                "victory.types.prevent_country_conquered",
                "Prevent {country} from being conquered",
            ).format(country=self._country_name(node.get("country")))
            return self._with_deadline(text, by_turn)

        if node_type == "prevent_location_captured":
            text = self._tr(
                "victory.types.prevent_location_captured",
                "Prevent {location} from being captured",
            ).format(location=self._location_name(node.get("location")))
            return self._with_deadline(text, by_turn)

        if node_type == "ally_country":
            text = self._tr("victory.types.ally_country", "Ally {country}").format(
                country=self._country_name(node.get("country"))
            )
            return self._with_deadline(text, by_turn)

        if node_type == "control_n_countries":
            text = self._tr("victory.types.control_n_countries", "Control {count} countries").format(
                count=int(node.get("count", 0) or 0)
            )
            return self._with_deadline(text, by_turn)

        if node_type == "prevent_country_control":
            text = self._tr("victory.types.prevent_country_control", "Prevent enemy control of {country}").format(
                country=self._country_name(node.get("country"))
            )
            return self._with_deadline(text, by_turn)

        if node_type in ("destroy_unit_score", "survive_unit_score", "escape_unit_score"):
            return self._format_unit_score_leaf(node, node_type)

        return str(node)

    def _format_unit_score_leaf(self, node: dict[str, Any], node_type: str) -> str:
        country = node.get("country")
        unit_types = self._unit_types_label(node.get("unit_types"))
        min_points = int(node.get("min_points", 0) or 0)
        by_turn = node.get("by_turn")

        if node_type == "destroy_unit_score":
            template = self._tr(
                "victory.types.destroy_unit_score",
                "Destroy enemy {unit_types}{country_part} for at least {min_points} points",
            )
            text = template.format(
                unit_types=unit_types,
                country_part=self._country_part(country),
                min_points=min_points,
            )
            return self._with_deadline(text, by_turn)

        if node_type == "survive_unit_score":
            template = self._tr(
                "victory.types.survive_unit_score",
                "Survive with friendly {unit_types}{country_part} for at least {min_points} points",
            )
            text = template.format(
                unit_types=unit_types,
                country_part=self._country_part(country),
                min_points=min_points,
            )
            return self._with_deadline(text, by_turn)

        escape_hexes = node.get("hexes") or node.get("escape_hexes") or []
        escape_list = self._format_hexes(escape_hexes)
        template = self._tr(
            "victory.types.escape_unit_score",
            "Escape to {hexes} with friendly {unit_types}{country_part} for at least {min_points} points",
        )
        text = template.format(
            hexes=escape_list,
            unit_types=unit_types,
            country_part=self._country_part(country),
            min_points=min_points,
        )
        return self._with_deadline(text, by_turn)

    def _with_deadline(self, text: str, by_turn: Any) -> str:
        if by_turn is None:
            return text
        suffix = self._tr("victory.labels.by_turn", "by turn {turn}").format(turn=by_turn)
        return f"{text} ({suffix})"

    def _format_hexes(self, values: Any) -> str:
        if not isinstance(values, list) or not values:
            return "[]"
        pairs = []
        for item in values:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append(f"[{item[0]},{item[1]}]")
        return ", ".join(pairs) if pairs else "[]"

    def _unit_types_label(self, raw: Any) -> str:
        if isinstance(raw, list):
            tokens = [str(v).strip().lower() for v in raw]
        elif raw is None:
            tokens = ["units"]
        else:
            tokens = [str(raw).strip().lower()]
        if not tokens:
            tokens = ["units"]
        out = []
        for token in tokens:
            if token in {"unit", "units"}:
                out.append(self._tr("victory.unit_types.units", "units"))
            elif token in {"fleet", "fleets", "ship", "ships"}:
                out.append(self._tr("victory.unit_types.fleets", "fleets"))
            elif token in {"leader", "leaders"}:
                out.append(self._tr("victory.unit_types.leaders", "leaders"))
            else:
                out.append(token)
        return ", ".join(out)

    def _country_name(self, country_id: Any) -> str:
        key = str(country_id or "").strip().lower()
        if not key:
            return ""
        if hasattr(self.translator, "get_country_name"):
            return self.translator.get_country_name(key)
        return key

    def _location_name(self, location_id: Any) -> str:
        key = str(location_id or "").strip().lower()
        if not key:
            return ""
        return self._tr(f"locations.{key}", key)

    def _country_part(self, country_id: Any) -> str:
        if not country_id:
            return ""
        template = self._tr("victory.labels.country_filter", " from {country}")
        return template.format(country=self._country_name(country_id))

    def _tr(self, path: str, default: str) -> str:
        parts = path.split(".")
        cursor: Any = self._tdata
        for part in parts:
            if not isinstance(cursor, dict) or part not in cursor:
                return default
            cursor = cursor.get(part)
        return cursor if isinstance(cursor, str) else default
