import yaml
import os
from src.content.tools import to_roman
from src.content.config import LOCALE_DIR, DEFAULT_LANG

_shared_translator = None


def get_translator() -> "Translator":
    """Return the application-wide Translator, lazily created if not set."""
    global _shared_translator
    if _shared_translator is None:
        _shared_translator = Translator()
    return _shared_translator


def set_translator(translator: "Translator") -> None:
    """Set the application-wide Translator used by modules with no direct access."""
    global _shared_translator
    _shared_translator = translator


class _UnitField:
    """A template token with several render forms, chosen via the format spec.

    - ``{land}``         → name form (e.g. "Silvanesti")
    - ``{land:adjective}`` → adjective/gentilicio form (e.g. "Nerakan")
    - ``{land:prep}``    → prepositional form (prep + adjective, e.g. "de Neraka")
    """

    __slots__ = ("name", "adjective", "prep")

    def __init__(self, name="", adjective="", prep=""):
        self.name = name
        self.adjective = adjective
        self.prep = prep

    def __format__(self, spec: str) -> str:
        if spec == "adjective":
            return self.adjective or self.name
        if spec == "prep":
            return f"{self.prep} {self.adjective}".strip() if self.adjective else ""
        return self.name

    def __bool__(self) -> bool:
        return bool(self.name)


class Translator:
    def __init__(self, lang_code=DEFAULT_LANG):
        self.lang_code = lang_code
        self.translations = self._load_translations()

    def _load_translations(self):
        path = os.path.join(LOCALE_DIR, f"{self.lang_code}.yaml")
    
        # Fallback if the system locale file is missing
        if not os.path.exists(path):
            print(f"Locale '{self.lang_code}' not found, falling back to '{DEFAULT_LANG}'.")
            path = os.path.join(LOCALE_DIR, f"{DEFAULT_LANG}.yaml")
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def format_unit_name(self, unit, mode='log'):
        """Build a localized unit label using the per-language templates in
        ``units``: ``{mode}_format_generic`` by default, overridden by
        ``{mode}_format_flight`` for dragon wings, or ``{mode}_format_named``
        for hand-authored names.

        ``unit`` may be a real Unit (fields come from its spec) or a proxy
        object exposing ``id``/``ordinal``/``is_leader`` with ``spec=None``
        (fields are then parsed from the id tokens, as the counters do).

        Returns ``None`` when no template applies or the template fails to
        render, so callers can fall back to a legacy formatter.
        """
        fields = self._unit_fields(unit)
        named = self.translations.get('unit_names', {}).get(getattr(unit, "id", ""))
        section = self.translations.get('units', {})
        key = "log" if mode == "log" else "counter"

        if named:
            template = section.get(f'{key}_format_named')
            if template is None:
                return None
            fields["name"] = _UnitField(named)
            fields["ordinal"] = _UnitField()
            return self._render_template(template, fields)

        type_tok = fields.get("_type", "")
        race_tok = fields.get("_race", "")
        if type_tok == "wing" and race_tok == "dragon":
            template = section.get(f'{key}_format_flight')
        else:
            template = None
        if template is None:
            template = section.get(f'{key}_format_generic')
        if template is None:
            return None
        if unit.is_leader():
            fields["ordinal"] = _UnitField()
        return self._render_template(template, fields)

    def _render_template(self, template: str, fields: dict):
        try:
            return template.format_map(fields).replace("  ", " ").strip()
        except (KeyError, ValueError):
            return None

    def _unit_fields(self, unit) -> dict:
        """Extract the template fields from a unit (spec-based, or id-parsed)."""
        spec = getattr(unit, "spec", None)
        if spec is not None:
            land_token = getattr(unit, "land", None) or getattr(spec, "dragonflight", None) or ""
            race_token = getattr(spec, "race", "") or ""
            type_token = getattr(spec, "unit_type", "") or ""
        else:
            parts = str(getattr(unit, "id", "")).split("_")
            land_token = parts[0] if parts else ""
            race_token = parts[1] if len(parts) > 1 else ""
            type_token = parts[2] if len(parts) > 2 else ""
        return {
            "ordinal": _UnitField(to_roman(getattr(unit, "ordinal", None)) if getattr(unit, "ordinal", None) else ""),
            "name": _UnitField(),
            "land": self._locale_field(land_token, "countries"),
            "race": self._locale_field(race_token, "races"),
            "type": self._locale_field(type_token, "unit_types"),
            "_type": type_token,
            "_race": race_token,
        }

    def _locale_field(self, token: str, table: str) -> _UnitField:
        """Resolve a slug token into a localizable field for the given table."""
        node = (self.translations.get(table, {}) or {}).get(token, {})
        if not isinstance(node, dict):
            node = {}
        name = node.get("name") or ""
        adjective = node.get("adjective") or ""
        if not name:
            name = token.capitalize() if token else ""
        if not adjective:
            adjective = name
        prep = node.get("prep") if isinstance(node.get("prep"), str) else None
        if prep is None:
            prep = (self.translations.get("units", {}) or {}).get("genitive_preposition", "de")
        return _UnitField(name, adjective, prep)

    def get_country_name(self, country_id: str) -> str:
        """Returns the translated name of the country."""
        return self.translations.get('countries', {}).get(country_id, {}).get('name', country_id)

    def get_country_adjective(self, country_id: str) -> str:
        """Returns the translated adjective of the country, falling back to its name.

        Returns an empty string when the country is unknown.
        """
        node = self.translations.get('countries', {}).get(country_id, {})
        if not isinstance(node, dict):
            return ""
        return node.get('adjective') or node.get('name', "")

    def get_race_name(self, race_id: str) -> str:
        """Returns the translated singular name of the race, or an empty string."""
        return self.translations.get('races', {}).get(race_id, {}).get('name', "")

    def get_race_plural_name(self, race_id: str) -> str:
        """Returns the translated plural name of the race, or an empty string."""
        return self.translations.get('races', {}).get(race_id, {}).get('plural', "")

    def get_race_adjective(self, race_id: str) -> str:
        """Returns the translated adjective of the race, or an empty string."""
        return self.translations.get('races', {}).get(race_id, {}).get('adjective', "")

    def get_unit_type_name(self, type_id: str) -> str:
        """Returns the translated name of the unit type, or an empty string."""
        return self.translations.get('unit_types', {}).get(type_id, {}).get('name', "")

    def get_asset_name(self, asset_id: str) -> str:
        """Returns the translated name of the asset."""
        return self.translations.get('assets', {}).get(asset_id, asset_id)

    def get_event_name(self, event_id: str) -> str:
        """Returns the translated name of the event."""
        return self.translations.get('events', {}).get(event_id, event_id)

    def get_capital_name(self, capital_id: str) -> str:
        """Returns the translated name of the capital city."""
        return self.translations.get('capitals', {}).get(capital_id, capital_id)

    def get_text(self, category: str, key: str) -> str:
        """Generic fetcher for UI strings like 'strength' or 'allegiance'."""
        return self.translations.get(category, {}).get(key, key)

    def tr(self, key: str, default: str = "", **kwargs) -> str:
        """
        Dotted-path translation helper, e.g. tr("dialogs.diplomacy.title").
        Falls back to `default` or the key itself when missing.
        """
        node = self.translations
        for part in str(key).split("."):
            if not isinstance(node, dict) or part not in node:
                text = default or key
                return text.format(**kwargs) if kwargs else text
            node = node.get(part)

        if not isinstance(node, str):
            text = default or key
            return text.format(**kwargs) if kwargs else text

        return node.format(**kwargs) if kwargs else node
