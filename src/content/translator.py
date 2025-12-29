import yaml
from utils import to_roman

class Translator:
    def __init__(self, lang_code='en'):
        self.lang_code = lang_code
        self.translations = self._load_translations()

    def _load_translations(self):
        path = f"data/locale/{self.lang_code}.yaml"
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
