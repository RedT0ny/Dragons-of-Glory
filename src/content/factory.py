from . import loader
from .specs import *
from .config import UNITS_DATA, COUNTRIES_DATA
from src.content.constants import HL, WS
from src.game.country import Country
from src.game.unit import Unit, Leader, Wing, Hero, Fleet, Wizard, Army, FlyingCitadel

def create_scenario_items(scenario_spec: ScenarioSpec) -> Tuple[List[Unit], Dict[str, Country]]:
    """
    Creates live objects from blueprints.
    Returns the list of units and the dictionary of countries.
    """
    # 1. Get Blueprints from Loader
    unit_specs = loader.resolve_scenario_units(scenario_spec, UNITS_DATA)
    country_specs = loader.resolve_scenario_countries(scenario_spec, COUNTRIES_DATA)

    # 2. Convert Specs to Live Objects
    live_countries = {
        c_spec.id: Country(c_spec) for c_spec in country_specs.values()
    }
    live_units = []
    
    # Class mapping based on UnitType string in spec
    # This logic was previously hidden or implicit, now we make it explicit
    class_map = {
        UnitType.INFANTRY: Army,
        UnitType.CAVALRY: Army,
        UnitType.GENERAL: Leader,
        UnitType.ADMIRAL: Leader, # Or Fleet depending on your logic, but likely Leader
        UnitType.EMPEROR: Leader,
        UnitType.HIGHLORD: Leader,
        UnitType.WIZARD: Wizard,
        UnitType.HERO: Hero,
        UnitType.WING: Wing,
        UnitType.FLEET: Fleet,
        UnitType.CITADEL: FlyingCitadel
    }

    for s in unit_specs:
        # We assume loader has already done string-to-enum conversion for unit_type/race 
        # inside resolve_scenario_units or we do it here if s is raw data.
        # Assuming 's' is a UnitSpec object (dataclass) here.
        
        # If 's' is UnitSpec, the enums are strings, so we convert them for the logic check
        # But we pass the raw spec to the unit class, which handles conversion via properties or in init
        
        # Determine the target class
        u_type_str = s.unit_type
        # Helper to safely get enum
        u_type = loader._string_to_enum(u_type_str, UnitType) if u_type_str else None
        
        target_class = class_map.get(u_type, Unit) # Default to generic Unit if type not found

        # Factory logic: Pass the SPEC directly
        # The 's' variable IS the UnitSpec object
        new_unit = target_class(spec=s, ordinal=s.ordinal)

        # Set initial status: Units for active sides start as READY (available for placement)
        if new_unit.allegiance in [HL, WS]:
                new_unit.ready()

        live_units.append(new_unit)

    # 3. Create scenario items
    return live_units, live_countries