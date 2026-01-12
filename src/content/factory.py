from .specs import *
from . import loader
from .config import UNITS_DATA, COUNTRIES_DATA
from src.game.scenario import Scenario
from src.game.unit import Unit

def create_scenario(scenario_spec: ScenarioSpec) -> Scenario:
    """
    The true Factory: Creates live objects from blueprints.
    """
    # 1. Get Blueprints from Loader
    unit_blueprints = loader.resolve_scenario_units(scenario_spec, UNITS_DATA)
    country_blueprints = loader.load_countries_yaml(COUNTRIES_DATA)

    # 2. Breathe life into Units
    live_units = []
    for s in unit_blueprints:
        # Factory logic: Choose the right class/init based on spec data
        live_units.append(Unit(
            unit_id=s.id,
            unit_type=s.unit_type,
            combat_rating=s.combat_rating,
            tactical_rating=s.tactical_rating,
            movement=s.movement,
            race=s.race,
            land=s.country,
            allegiance=s.allegiance,
            ordinal=s.ordinal
        ))

    # 3. Create the Scenario
    return Scenario(
        scenario_id=scenario_spec.id,
        description=scenario_spec.description,
        units=live_units,
        countries=country_blueprints, # Can also convert these to Country objects here
        setup=scenario_spec.setup,
        map_subset=scenario_spec.map_subset
    )