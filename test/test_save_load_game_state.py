import tempfile
from pathlib import Path

from src.content.config import SCENARIOS_DIR
from src.content.constants import HL, WS
from src.content.loader import load_scenario_yaml
from src.content.specs import GamePhase, UnitState, UnitType
from src.game.game_state import GameState
from src.game.map import Hex


def _scenario_spec():
    scenario_path = Path(SCENARIOS_DIR) / "campaign_0_war_of_the_lance.yaml"
    return load_scenario_yaml(str(scenario_path))


def _unit_key(unit):
    return unit.id, unit.ordinal


def test_save_load_roundtrip_restores_core_runtime_state():
    gs = GameState()
    gs.load_scenario(_scenario_spec())

    gs.turn = 7
    gs.phase = GamePhase.MOVEMENT
    gs.active_player = WS
    gs.initiative_winner = HL
    gs.second_player_has_acted = True
    gs.activation_bonuses = {HL: 2, WS: 1}
    gs.combat_bonuses = {HL: 3, WS: 0}

    # Country runtime state
    country = next(iter(gs.countries.values()))
    country.allegiance = WS
    country.conquered = True
    if country.locations:
        first_loc = next(iter(country.locations.values()))
        first_loc.occupier = HL

    # Units runtime state (including transport and fleet river mode)
    fleet = next(u for u in gs.units if u.unit_type == UnitType.FLEET)
    army = next(u for u in gs.units if hasattr(u, "is_army") and u.is_army())
    gs.map.remove_unit_from_spatial_map(fleet)
    gs.map.remove_unit_from_spatial_map(army)

    fleet.status = UnitState.ACTIVE
    fleet.position = (20, 20)
    fleet.movement_points = 9
    fleet.river_hexside = ((1, 1), (1, 2))
    fleet.passengers = [army]

    army.status = UnitState.ACTIVE
    army.position = fleet.position
    army.is_transported = True
    army.transport_host = fleet

    gs.map.add_unit_to_spatial_map(fleet)

    # Player assets + event progress
    if gs.artifact_pool:
        asset_id = next(iter(gs.artifact_pool.keys()))
        gs.players[HL].grant_asset(asset_id, gs)
        assert asset_id in gs.players[HL].assets

    if gs.strategic_event_pool:
        evt = gs.strategic_event_pool[0]
        evt.occurrence_count = 2
        evt.is_active = False
        gs.completed_event_ids.add(evt.id)

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
        save_path = tmp.name
    try:
        gs.save_state(save_path)

        loaded = GameState()
        loaded.load_state(save_path)

        assert loaded.turn == 7
        assert loaded.phase == GamePhase.MOVEMENT
        assert loaded.active_player == WS
        assert loaded.initiative_winner == HL
        assert loaded.second_player_has_acted is True
        assert loaded.activation_bonuses == {HL: 2, WS: 1}
        assert loaded.combat_bonuses == {HL: 3, WS: 0}

        loaded_country = loaded.countries[country.id]
        assert loaded_country.allegiance == WS
        assert loaded_country.conquered is True
        if country.locations:
            assert loaded_country.locations[first_loc.id].occupier == HL

        by_key = {_unit_key(u): u for u in loaded.units}
        loaded_fleet = by_key[_unit_key(fleet)]
        loaded_army = by_key[_unit_key(army)]
        assert loaded_fleet.position == (20, 20)
        assert loaded_fleet.movement_points == 9
        assert loaded_fleet.river_hexside == ((1, 1), (1, 2))
        assert loaded_army.is_transported is True
        assert loaded_army.transport_host == loaded_fleet
        assert loaded_army in loaded_fleet.passengers

        # Transported units should not be present in spatial map
        fleet_hex = Hex.offset_to_axial(*loaded_fleet.position)
        on_hex = loaded.map.get_units_in_hex(fleet_hex.q, fleet_hex.r)
        assert loaded_fleet in on_hex
        assert loaded_army not in on_hex

        if gs.artifact_pool:
            assert asset_id in loaded.players[HL].assets

        if gs.strategic_event_pool:
            loaded_evt = next(e for e in loaded.strategic_event_pool if e.id == evt.id)
            assert loaded_evt.occurrence_count == 2
            assert loaded_evt.is_active is False
            assert evt.id in loaded.completed_event_ids
    finally:
        Path(save_path).unlink(missing_ok=True)
