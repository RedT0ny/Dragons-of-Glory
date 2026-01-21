from . import loader
from .specs import *
from .config import UNITS_DATA, COUNTRIES_DATA
from src.game.scenario import Scenario
from src.game.country import Country
from src.game.unit import Unit, Leader, Wing, Hero, Fleet, Wizard, Army, FlyingCitadel

def create_scenario(scenario_spec: ScenarioSpec) -> Scenario:
    """
    Creates live objects from blueprints.
    """
    # 1. Get Blueprints from Loader
    unit_specs = loader.resolve_scenario_units(scenario_spec, UNITS_DATA)
    country_specs = loader.load_countries_yaml(COUNTRIES_DATA)

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
        UnitType.CITADEL: FlyingCitadel # Nested class
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
        live_units.append(target_class(spec=s, ordinal=s.ordinal))

    # 3. Create the Scenario
    scenario = Scenario(
        scenario_id=scenario_spec.id,
        description=scenario_spec.description,
        units=live_units,
        countries=country_specs, # Can also convert these to Country objects here
        setup=scenario_spec.setup,
        map_subset=scenario_spec.map_subset
    )

    # 4. Attach map bounds to scenario for easy access
    if scenario_spec.map_subset:
        scenario.map_width = scenario_spec.map_subset['x_range'][1] - scenario_spec.map_subset['x_range'][0] + 1
        scenario.map_height = scenario_spec.map_subset['y_range'][1] - scenario_spec.map_subset['y_range'][0] + 1
    else:
        from src.content.config import MAP_WIDTH, MAP_HEIGHT
        scenario.map_width = MAP_WIDTH
        scenario.map_height = MAP_HEIGHT

    return scenario