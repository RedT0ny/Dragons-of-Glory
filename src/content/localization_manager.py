import yaml
from utils import to_roman

class LocalizationManager:
    def __init__(self, lang_code='en'):
        self.lang_code = lang_code
        self.translations = self._load_translations()

    def _load_translations(self):
        path = f"data/locale/{self.lang_code}.yaml"
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def format_unit_name(self, unit, mode='log'):
        """
        Formatea el nombre de la unidad según el idioma y el modo (log/counter).
        """
        ordinal_roman = to_roman(unit.ordinal)
        
        # Elegir la plantilla (named vs generic)
        key_type = "named" if unit.name and unit.name.strip() else "generic"
        template = self.translations['units'][f'{mode}_format_{key_type}']
        
        # Rellenar la plantilla
        return template.format(
            ordinal=ordinal_roman,
            name=unit.name,
            land=unit.land if unit.land else unit.race.capitalize(),
            race=unit.race,
            type=unit.unit_type
        )
