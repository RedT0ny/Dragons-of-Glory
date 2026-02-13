from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import TerrainType, UnitType
from src.game.map import Board, Hex


def _set_terrain(board: Board, col: int, row: int, terrain: str):
    hex_obj = Hex.offset_to_axial(col, row)
    board.grid[(hex_obj.q, hex_obj.r)] = terrain


def _army(allegiance, *, affinity=None):
    return SimpleNamespace(
        allegiance=allegiance,
        unit_type=UnitType.INFANTRY,
        terrain_affinity=affinity,
        is_army=lambda: True,
        is_leader=lambda: False,
    )


def _wing(allegiance):
    return SimpleNamespace(
        allegiance=allegiance,
        unit_type=UnitType.WING,
        movement=4,
        movement_points=4,
    )


def test_mountain_terrain_implies_mountain_hexside_for_ground_cost():
    board = Board(width=10, height=10)
    start = Hex.offset_to_axial(4, 4)
    target = start.neighbors()[0]
    target_col, target_row = target.axial_to_offset()
    _set_terrain(board, target_col, target_row, TerrainType.MOUNTAIN.value)

    unit = _army(HL)

    assert board._get_ground_movement_cost(unit, start, target) == float("inf")


def test_pass_overrides_implicit_mountain_hexside():
    board = Board(width=10, height=10)
    start = Hex.offset_to_axial(4, 4)
    target = start.neighbors()[0]
    target_col, target_row = target.axial_to_offset()
    _set_terrain(board, target_col, target_row, TerrainType.MOUNTAIN.value)
    board.add_hexside(start.q, start.r, target.q, target.r, "pass")

    unit = _army(HL)

    assert board._get_ground_movement_cost(unit, start, target) == 2


def test_mountain_terrain_blocks_enemy_adjacency_unless_pass():
    board = Board(width=10, height=10)
    start = Hex.offset_to_axial(4, 4)
    enemy_hex = start.neighbors()[0]
    enemy_col, enemy_row = enemy_hex.axial_to_offset()
    _set_terrain(board, enemy_col, enemy_row, TerrainType.MOUNTAIN.value)
    board.unit_map[(enemy_hex.q, enemy_hex.r)] = [_army(WS)]

    moving_army = _army(HL)
    assert board.is_adjacent_to_enemy(start, moving_army) is False

    board.add_hexside(start.q, start.r, enemy_hex.q, enemy_hex.r, "pass")
    assert board.is_adjacent_to_enemy(start, moving_army) is True


def test_wing_pays_extra_mp_across_implicit_mountain_hexside():
    board = Board(width=10, height=10)
    wing = _wing(HL)
    start = Hex.offset_to_axial(4, 4)
    target = start.neighbors()[0]
    target_col, target_row = target.axial_to_offset()
    _set_terrain(board, target_col, target_row, TerrainType.MOUNTAIN.value)

    assert board._get_wing_movement_cost(wing, start, target) == 2

