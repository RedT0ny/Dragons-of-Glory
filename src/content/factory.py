from . import loader
from .specs import *
from .config import UNITS_DATA, COUNTRIES_DATA
from src.game.scenario import Scenario
from src.game.unit import Unit

def create_scenario(scenario_spec: ScenarioSpec) -> Scenario:
    """
    Creates live objects from blueprints.
    """
    # 1. Get Blueprints from Loader
    unit_blueprints = loader.resolve_scenario_units(scenario_spec, UNITS_DATA)
    country_blueprints = loader.load_countries_yaml(COUNTRIES_DATA)

    # 2. Breathe life into Units
    live_units = []
    for s in unit_blueprints:
        # Convert string values to Enums
        unit_type_enum = loader._string_to_enum(s.unit_type, UnitType)
        race_enum = loader._string_to_enum(s.race, UnitRace)
        status_enum = loader._string_to_enum(s.status, UnitState) if s.status else UnitState.INACTIVE

        # Factory logic: Choose the right class/init based on spec data
        live_units.append(Unit(
            unit_id=s.id,
            unit_type=unit_type_enum,
            combat_rating=s.combat_rating,
            tactical_rating=s.tactical_rating,
            movement=s.movement,
            race=race_enum,
            land=s.country,
            allegiance=s.allegiance,
            ordinal=s.ordinal,
            status=status_enum
        ))

    # 3. Create the Scenario
    scenario = Scenario(
        scenario_id=scenario_spec.id,
        description=scenario_spec.description,
        units=live_units,
        countries=country_blueprints, # Can also convert these to Country objects here
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