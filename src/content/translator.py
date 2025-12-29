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
        """
        Formats the unit name. 
        If named: "III Lord Soth"
        If generic: "III Silvanesti Elf Infantry"
        """
        ordinal_roman = to_roman(unit.ordinal)
        
        # 1. Determine if it's a named unit or generic
        # A unit is "generic" if the CSV name field was empty or set to the format string
        is_generic = not unit.name or "ordinal" in unit.name.lower()
        key_type = "generic" if is_generic else "named"
        template = self.translations['units'][f'{mode}_format_{key_type}']
        
        # 2. Get Translated components for generic names
        # We fetch from the 'races', 'unit_types', and 'countries' sections of en.yaml/es.yaml
        land_name = self.get_country_name(unit.country) if unit.country else ""
        race_name = self.translations.get('races', {}).get(unit.race, {}).get('name', unit.race)
        type_name = self.translations.get('unit_types', {}).get(unit.unit_type, {}).get('name', unit.unit_type)

        # 3. Fill the template
        # Template example: "{ordinal} {land} {race} {type}"
        return template.format(
            ordinal=ordinal_roman,
            name=unit.name,
            land=land_name,
            race=race_name,
            type=type_name
        ).strip().replace("  ", " ") # Clean up double spaces if land is missing

    def get_country_name(self, country_id: str) -> str:
        """Returns the translated name of the country."""
        return self.translations.get('countries', {}).get(country_id, {}).get('name', country_id)

    def get_capital_name(self, capital_id: str) -> str:
        """Returns the translated name of the capital city."""
        return self.translations.get('capitals', {}).get(capital_id, capital_id)

    def get_text(self, category: str, key: str) -> str:
        """Generic fetcher for UI strings like 'strength' or 'allegiance'."""
        return self.translations.get(category, {}).get(key, key)
