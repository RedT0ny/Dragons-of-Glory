from dataclasses import asdict
from typing import Callable, Dict, List, Optional, Set, Tuple
import random
import re
from . import loader
from .specs import *
from .config import UNITS_DATA, COUNTRIES_DATA, MAP_TERRAIN_DATA, MAP_CONFIG_DATA, EVENTS_DATA, ARTIFACTS_DATA
from src.content.constants import HL, WS
from src.game.country import Country
from src.game.event import Event, Asset
from src.game.map import Board
from src.game.unit import Unit, Leader, Wing, Hero, Fleet, Wizard, Army, FlyingCitadel


_RANDOM_PLACEHOLDER_RE = re.compile(r"\{random:([^{}]+)\}")

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
    
    class_map = _get_unit_class_map()

    for s in unit_specs:
        # We assume loader has already done string-to-enum conversion for unit_type/race 
        # inside resolve_scenario_units or we do it here if s is raw data.
        # Assuming 's' is a UnitSpec object (dataclass) here.
        
        # If 's' is UnitSpec, the enums are strings, so we convert them for the logic check
        # But we pass the raw spec to the unit class, which handles conversion via properties or in init
        
        target_class = _resolve_unit_class(s, class_map)

        # Factory logic: Pass the SPEC directly
        # The 's' variable IS the UnitSpec object
        new_unit = target_class(spec=s, ordinal=s.ordinal)

        # Set initial status: Units for active sides start as READY (available for placement)
        if new_unit.allegiance in [HL, WS]:
                new_unit.ready()

        live_units.append(new_unit)

    # 3. Create scenario items
    return live_units, live_countries

def _get_unit_class_map():
    # Class mapping based on UnitType string in spec
    # This logic was previously hidden or implicit, now we make it explicit
    return {
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

def _resolve_unit_class(spec, class_map):
    u_type_str = spec.unit_type
    u_type = loader._string_to_enum(u_type_str, UnitType) if u_type_str else None
    return class_map.get(u_type, Unit)

def create_units_from_specs(specs: List[UnitSpec], allegiance: Optional[str] = None,
                            countries: Optional[Dict[str, Country]] = None,
                            ready: bool = False) -> List[Unit]:
    if not specs:
        return []

    class_map = _get_unit_class_map()
    created = []
    for spec in specs:
        new_spec = UnitSpec(**asdict(spec))
        if allegiance:
            new_spec.allegiance = allegiance

        target_class = _resolve_unit_class(new_spec, class_map)
        new_unit = target_class(spec=new_spec, ordinal=new_spec.ordinal)

        if ready:
            new_unit.ready()
        if allegiance:
            new_unit.allegiance = allegiance

        if countries and new_unit.land and new_unit.land in countries:
            countries[new_unit.land].add_unit(new_unit)

        created.append(new_unit)
    return created


def create_asset_from_spec(spec: AssetSpec) -> Asset:
    """
    Creates a live Asset instance from an AssetSpec blueprint.
    Supports dynamic placeholder materialization such as:
    {random:option 1|option 2|...}
    """
    materialized_spec = _materialize_asset_spec_random_fields(spec)
    return Asset(materialized_spec)


def _materialize_asset_spec_random_fields(spec: AssetSpec) -> AssetSpec:
    raw = asdict(spec)
    processed = _materialize_random_placeholders(raw)
    return AssetSpec(**processed)


def _materialize_random_placeholders(value):
    if isinstance(value, str):
        return _replace_random_tokens(value)
    if isinstance(value, list):
        return [_materialize_random_placeholders(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_materialize_random_placeholders(v) for v in value)
    if isinstance(value, dict):
        return {k: _materialize_random_placeholders(v) for k, v in value.items()}
    return value


def _replace_random_tokens(text: str) -> str:
    def _pick(match: re.Match) -> str:
        options_raw = match.group(1).split("|")
        options = [o.strip() for o in options_raw if o.strip()]
        if not options:
            return ""
        return random.choice(options)

    return _RANDOM_PLACEHOLDER_RE.sub(_pick, text)

class UnitCatalog:
    def __init__(self, units_csv_path: str = UNITS_DATA, loader_func: Optional[Callable] = None):
        self.units_csv_path = units_csv_path
        self._loader_func = loader_func or loader.load_units_catalog

    def get_catalog(self) -> List[UnitSpec]:
        return self._loader_func(self.units_csv_path, use_cache=True)

    def get_available_specs(self, existing_ids: Set[str]) -> List[UnitSpec]:
        return [s for s in self.get_catalog() if s.id not in existing_ids]

class ScenarioBuilder:
    def build(self, game_state, scenario_spec):
        game_state.scenario_spec = scenario_spec

        # Setup live objects via Factory
        game_state.units, game_state.countries = create_scenario_items(scenario_spec)

        # Apply Draconian scenario rules (ready count, production flag)
        game_state._apply_draconian_setup()

        # Load Artifacts Catalog
        game_state.artifact_pool = loader.load_artifacts_yaml(ARTIFACTS_DATA)

        # Setup the map
        bounds = game_state.get_map_bounds()
        width, height = game_state.get_map_dimensions()
        offset_col = bounds["x_range"][0]
        offset_row = bounds["y_range"][0]

        if game_state.scenario_spec and game_state.scenario_spec.map_subset:
            game_state._apply_map_subset_offsets(offset_col, offset_row, width, height)

        # Initialize the actual HexGrid model
        game_state.map = Board(width, height, offset_col=offset_col, offset_row=offset_row)

        # Populate Terrain
        terrain_data = loader.load_terrain_csv(MAP_TERRAIN_DATA)
        game_state.map.populate_terrain(terrain_data)

        # Populate Hexsides (Rivers, Mountains)
        map_config = loader.load_map_config(MAP_CONFIG_DATA)
        game_state.map.populate_hexsides(map_config.hexsides)

        # Populate Locations (Special + Country)
        special_locations = map_config.special_locations
        if game_state.scenario_spec and game_state.scenario_spec.map_subset:
            special_locations = game_state._adjust_special_locations(
                special_locations, offset_col, offset_row
            )
        game_state.map.populate_locations(special_locations, game_state.countries)

        # Initialize Players (after map offsets are applied to the spec)
        game_state._initialize_players()

        # Load Strategic Events
        event_specs = loader.resolve_scenario_events(game_state.scenario_spec, EVENTS_DATA)
        game_state.strategic_event_pool = []
        for s in event_specs:
            # We pass generic lambdas that delegate back to GameState logic
            evt = Event(s,
                        trigger_func=lambda gs, s=s: gs.check_event_trigger_conditions(s.trigger_conditions),
                        effect_func=lambda gs, s=s: gs.apply_event_effect(s))
            game_state.strategic_event_pool.append(evt)

        # Register existing units on the map if they have positions
        for unit in game_state.units:
            if unit.position and unit.is_on_map:
                game_state.map.add_unit_to_spatial_map(unit)

        # Default to turn 1 if start_turn is missing from the scenario object
        game_state.turn = getattr(scenario_spec, 'start_turn', 1)

        # Determine initiative for Deployment
        init_str = getattr(scenario_spec, 'initiative_start', 'highlord').lower()

        # Start with Deployment Phase
        game_state.phase = GamePhase.DEPLOYMENT

        # The player WITHOUT initiative deploys first
        if init_str == WS:
            game_state.initiative_winner = WS
            game_state.active_player = HL
        else:
            game_state.initiative_winner = HL
            game_state.active_player = WS

        return game_state
