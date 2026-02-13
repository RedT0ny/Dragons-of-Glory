from types import SimpleNamespace

from src.content.constants import HL
from src.content.specs import TerrainType, UnitType
from src.game.combat import CombatResolver
from src.game.map import Board, Hex
from src.game.movement import MovementService


def _set_terrain(board: Board, col: int, row: int, terrain: str):
    hex_obj = Hex.offset_to_axial(col, row)
    board.grid[(hex_obj.q, hex_obj.r)] = terrain


def _wing_unit():
    return SimpleNamespace(
        id="wing_1",
        unit_type=UnitType.WING,
        allegiance=HL,
        movement=4,
        movement_points=4,
        position=(2, 2),
    )


def test_wing_cannot_land_on_ocean_hex():
    board = Board(width=8, height=8)
    wing = _wing_unit()
    target = Hex.offset_to_axial(3, 3)
    _set_terrain(board, 3, 3, "ocean")

    assert board.get_terrain(target) == TerrainType.OCEAN
    assert board.can_unit_land_on_hex(wing, target) is False


def test_wing_mountain_hexside_cost_is_plus_one():
    board = Board(width=8, height=8)
    wing = _wing_unit()
    start = Hex.offset_to_axial(2, 2)
    target = Hex.offset_to_axial(3, 2)
    _set_terrain(board, 3, 2, "grassland")
    board.add_hexside(start.q, start.r, target.q, target.r, "mountain")

    assert board._get_wing_movement_cost(wing, start, target) == 2


def test_movement_service_rejects_wing_ocean_destination():
    target = Hex(4, 4)
    fake_map = SimpleNamespace(
        can_unit_land_on_hex=lambda unit, h: False if h == target else True,
        find_shortest_path=lambda unit, start, goal: [goal],
        get_movement_cost=lambda unit, current, nxt: 1,
    )
    gs = SimpleNamespace(map=fake_map)
    service = MovementService(gs)
    wing = _wing_unit()
    wing.position = (1, 1)

    ok, reason = service._can_unit_reach_target(wing, target)

    assert ok is False
    assert "cannot end movement" in (reason or "")


def test_wing_retreat_options_exclude_ocean_hex():
    start = Hex(4, 4)
    ocean_neighbor = start.neighbors()[0]
    land_neighbor = start.neighbors()[1]

    def can_land(unit, hex_obj):
        return hex_obj != ocean_neighbor

    fake_map = SimpleNamespace(
        can_unit_land_on_hex=can_land,
        has_enemy_army=lambda hex_obj, allegiance: False,
        can_stack_move_to=lambda units, hex_obj: True,
        get_movement_cost=lambda unit, from_hex, to_hex: 1,
        get_units_in_hex=lambda q, r: [],
        is_adjacent_to_enemy=lambda hex_obj, unit: False,
    )
    game_state = SimpleNamespace(
        map=fake_map,
        is_hex_in_bounds=lambda col, row: True,
    )
    resolver = CombatResolver([], [], TerrainType.GRASSLAND, game_state=game_state)
    wing = _wing_unit()

    valid = resolver._get_valid_retreat_hexes(wing, start)

    assert ocean_neighbor not in valid
    assert land_neighbor in valid
