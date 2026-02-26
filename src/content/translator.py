import yaml
import os
from .utils import to_roman
from .config import LOCALE_DIR, DEFAULT_LANG

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
        ordinal_roman = to_roman(unit.ordinal)
        
        # If the unit's ID exists in our 'unit_names' translation table, it's a named unit.
        # Otherwise, it's a generic unit.
        named_display = self.translations.get('unit_names', {}).get(unit.id)
        
        if named_display:
            template = self.translations['units'][f'{mode}_format_named']
            return template.format(ordinal=ordinal_roman, name=named_display)
        else:
            template = self.translations['units'][f'{mode}_format_generic']
            return template.format(
                ordinal=ordinal_roman,
                land=self.get_country_name(unit.country) if unit.country else "",
                race=self.translations.get('races', {}).get(unit.race, {}).get('name', unit.race),
                type=self.translations.get('unit_types', {}).get(unit.unit_type, {}).get('name', unit.unit_type)
            ).strip().replace("  ", " ")

    def get_country_name(self, country_id: str) -> str:
        """Returns the translated name of the country."""
        return self.translations.get('countries', {}).get(country_id, {}).get('name', country_id)

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
