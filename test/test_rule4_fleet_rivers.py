from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitState, UnitType
from src.content.loader import load_scenario_yaml
from src.content.config import SCENARIOS_DIR
from src.game.game_state import GameState
from src.game.map import Board, Hex
from src.game.movement import MovementService
from pathlib import Path


def _fleet(allegiance, col, row, movement=4, moved=False):
    return SimpleNamespace(
        id=f"fleet_{allegiance}_{col}_{row}",
        unit_type=UnitType.FLEET,
        race=None,
        allegiance=allegiance,
        movement=movement,
        movement_points=movement,
        position=(col, row),
        river_hexside=None,
        moved_this_turn=moved,
        passengers=[],
        is_on_map=True,
        is_army=lambda: False,
    )


def _army(allegiance, col, row):
    return SimpleNamespace(
        id=f"army_{allegiance}_{col}_{row}",
        unit_type=UnitType.INFANTRY,
        race=None,
        allegiance=allegiance,
        movement=1,
        movement_points=1,
        position=(col, row),
        is_on_map=True,
        is_army=lambda: True,
    )


def _wing(allegiance, col, row, movement=4):
    return SimpleNamespace(
        id=f"wing_{allegiance}_{col}_{row}",
        unit_type=UnitType.WING,
        race=None,
        allegiance=allegiance,
        movement=movement,
        movement_points=movement,
        position=(col, row),
        is_on_map=True,
        is_army=lambda: False,
        is_leader=lambda: False,
    )


def _leader(allegiance, col, row, movement=2):
    return SimpleNamespace(
        id=f"leader_{allegiance}_{col}_{row}",
        unit_type=UnitType.HERO,
        race=None,
        allegiance=allegiance,
        movement=movement,
        movement_points=movement,
        position=(col, row),
        is_on_map=True,
        is_army=lambda: False,
        is_leader=lambda: True,
        terrain_affinity=None,
    )


def test_deep_river_path_cost_counts_hexsides_not_hexes():
    board = Board(width=12, height=12)
    start = Hex.offset_to_axial(2, 2)
    mid = start.neighbors()[0]
    end = mid.neighbors()[0]

    board.add_hexside(start.q, start.r, mid.q, mid.r, "deep_river")
    board.add_hexside(mid.q, mid.r, end.q, end.r, "deep_river")

    fleet = _fleet(HL, 2, 2, movement=3)
    path, cost = board.find_fleet_route(fleet, start, end)

    assert path
    assert cost == 2


def test_cannot_enter_deep_river_hexside_with_enemy_unit_on_bank():
    board = Board(width=12, height=12)
    start = Hex.offset_to_axial(2, 2)
    target = start.neighbors()[0]
    board.add_hexside(start.q, start.r, target.q, target.r, "deep_river")

    fleet = _fleet(HL, 2, 2, movement=3)
    enemy = _army(WS, *target.axial_to_offset())
    board.unit_map[(target.q, target.r)] = [enemy]

    _, cost = board.find_fleet_route(fleet, start, target)
    assert cost == float("inf")


def test_only_two_fleets_can_stack_on_same_river_hexside():
    board = Board(width=12, height=12)
    a = Hex.offset_to_axial(2, 2)
    b = a.neighbors()[0]
    board.add_hexside(a.q, a.r, b.q, b.r, "deep_river")
    river_side = board.get_hexside_key(a, b)

    f1 = _fleet(HL, *a.axial_to_offset())
    f2 = _fleet(HL, *b.axial_to_offset())
    f1.river_hexside = river_side
    f2.river_hexside = river_side
    board.unit_map[(a.q, a.r)] = [f1]
    board.unit_map[(b.q, b.r)] = [f2]

    moving = _fleet(HL, *a.axial_to_offset())
    _, cost = board.find_fleet_route(moving, a, b)
    assert cost == float("inf")


def test_river_fleet_bridge_requires_not_moved_this_turn():
    board = Board(width=12, height=12)
    a = Hex.offset_to_axial(2, 2)
    b = a.neighbors()[0]
    board.add_hexside(a.q, a.r, b.q, b.r, "deep_river")
    river_side = board.get_hexside_key(a, b)

    fleet = _fleet(HL, *a.axial_to_offset(), moved=False)
    fleet.river_hexside = river_side
    board.unit_map[(a.q, a.r)] = [fleet]
    assert board.is_ship_bridge(a, b, HL) is True

    fleet.moved_this_turn = True
    assert board.is_ship_bridge(a, b, HL) is False


def test_move_unit_updates_river_hexside_when_entering_deep_river():
    gs = GameState()
    gs.map = Board(width=12, height=12)
    gs.phase = GamePhase.MOVEMENT

    start = Hex.offset_to_axial(2, 2)
    target = start.neighbors()[0]
    gs.map.add_hexside(start.q, start.r, target.q, target.r, "deep_river")

    fleet = _fleet(HL, 2, 2, movement=3)
    gs.units = [fleet]
    gs.map.add_unit_to_spatial_map(fleet)

    gs.move_unit(fleet, target)

    assert fleet.position == target.axial_to_offset()
    assert fleet.river_hexside == gs.map.get_hexside_key(start, target)


def test_campaign_deep_river_chain_from_3240_is_reachable():
    gs = GameState()
    gs.load_scenario(load_scenario_yaml(str(Path(SCENARIOS_DIR) / "campaign_0_war_of_the_lance.yaml")))
    gs.phase = GamePhase.MOVEMENT

    fleet = next(u for u in gs.units if u.unit_type == UnitType.FLEET)
    gs.map.remove_unit_from_spatial_map(fleet)
    fleet.status = UnitState.ACTIVE
    fleet.allegiance = HL
    fleet.position = (32, 40)
    fleet.river_hexside = None
    fleet.moved_this_turn = False
    fleet.movement_points = 40
    gs.map.add_unit_to_spatial_map(fleet)

    reachable = {h.axial_to_offset() for h in gs.map.get_reachable_hexes([fleet])}
    for expected in [(31, 40), (30, 41), (31, 41), (31, 42), (32, 42)]:
        assert expected in reachable


def test_campaign_port_326_can_exit_via_river_to_324():
    gs = GameState()
    gs.load_scenario(load_scenario_yaml(str(Path(SCENARIOS_DIR) / "campaign_0_war_of_the_lance.yaml")))
    gs.phase = GamePhase.MOVEMENT

    fleet = next(u for u in gs.units if u.unit_type == UnitType.FLEET)
    gs.map.remove_unit_from_spatial_map(fleet)
    fleet.status = UnitState.ACTIVE
    fleet.allegiance = HL
    fleet.position = (3, 26)
    fleet.river_hexside = None
    fleet.moved_this_turn = False
    fleet.movement_points = 40
    gs.map.add_unit_to_spatial_map(fleet)

    target = Hex.offset_to_axial(3, 24)
    start = Hex.offset_to_axial(3, 26)
    _, cost = gs.map.find_fleet_route(fleet, start, target)
    reachable = {h.axial_to_offset() for h in gs.map.get_reachable_hexes([fleet])}

    assert cost == 2
    assert (3, 24) in reachable


def test_ground_army_entry_displaces_enemy_fleet_to_nearest_safe_water():
    gs = GameState()
    gs.map = Board(width=10, height=10)
    gs.phase = GamePhase.MOVEMENT

    terrain = {
        "2,2": "grassland",
        "3,2": "c_grassland",
        "4,2": "ocean",
        "3,1": "ocean",
        "4,1": "ocean",
        "3,3": "ocean",
    }
    gs.map.populate_terrain(terrain)

    army = _army(HL, 2, 2)
    enemy_fleet = _fleet(WS, 3, 2, movement=6)
    gs.units = [army, enemy_fleet]
    gs.map.add_unit_to_spatial_map(army)
    gs.map.add_unit_to_spatial_map(enemy_fleet)

    target_hex = Hex.offset_to_axial(3, 2)
    gs.move_unit(army, target_hex)

    assert army.position == (3, 2)
    assert enemy_fleet.position != (3, 2)
    displaced_hex = Hex.offset_to_axial(*enemy_fleet.position)
    assert not gs.map.has_enemy_army(displaced_hex, enemy_fleet.allegiance)


def test_non_ground_stack_cannot_enter_enemy_fleet_hex():
    board = Board(width=8, height=8)
    board.populate_terrain({"2,2": "grassland", "3,2": "grassland"})

    wing = _wing(HL, 2, 2)
    leader = _leader(HL, 2, 2)
    enemy_fleet = _fleet(WS, 3, 2)
    board.add_unit_to_spatial_map(wing)
    board.add_unit_to_spatial_map(leader)
    board.add_unit_to_spatial_map(enemy_fleet)

    target = Hex.offset_to_axial(3, 2)

    assert board.can_stack_move_to([wing, leader], target) is False
    reachable = {h.axial_to_offset() for h in board.get_reachable_hexes([wing, leader])}
    assert (3, 2) not in reachable


def test_movement_service_allows_ground_stack_into_enemy_fleet_hex():
    gs = GameState()
    gs.map = Board(width=10, height=10)
    gs.phase = GamePhase.MOVEMENT

    # Start and target are land/coastal; extra water provides a legal displacement destination.
    gs.map.populate_terrain({
        "2,2": "grassland",
        "3,2": "c_grassland",
        "4,2": "ocean",
        "3,1": "ocean",
        "3,3": "ocean",
    })

    army = _army(HL, 2, 2)
    leader = _leader(HL, 2, 2)
    enemy_fleet = _fleet(WS, 3, 2, movement=6)
    gs.units = [army, leader, enemy_fleet]
    gs.map.add_unit_to_spatial_map(army)
    gs.map.add_unit_to_spatial_map(leader)
    gs.map.add_unit_to_spatial_map(enemy_fleet)

    service = MovementService(gs)
    target_hex = Hex.offset_to_axial(3, 2)
    result = service.move_units_to_hex([leader, army], target_hex)

    assert result.errors == []
    assert army.position == (3, 2)
    assert leader.position == (3, 2)
    assert enemy_fleet.position != (3, 2)
