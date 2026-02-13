from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import UnitType
from src.game.map import Board, Hex


def _unit(allegiance, unit_type, *, is_army=False, is_leader=False):
    return SimpleNamespace(
        allegiance=allegiance,
        unit_type=unit_type,
        terrain_affinity=None,
        is_army=lambda: is_army,
        is_leader=lambda: is_leader,
    )


def test_has_enemy_army_ignores_non_army_units():
    board = Board(width=10, height=10)
    target = Hex.offset_to_axial(3, 3)
    enemy_leader = _unit(WS, UnitType.GENERAL, is_army=False, is_leader=True)
    board.unit_map[(target.q, target.r)] = [enemy_leader]

    assert board.has_enemy_army(target, HL) is False


def test_has_enemy_army_detects_enemy_army_units():
    board = Board(width=10, height=10)
    target = Hex.offset_to_axial(3, 3)
    enemy_army = _unit(WS, UnitType.INFANTRY, is_army=True)
    board.unit_map[(target.q, target.r)] = [enemy_army]

    assert board.has_enemy_army(target, HL) is True


def test_zoc_restriction_applies_to_army_but_not_leader():
    board = Board(width=10, height=10)
    start = Hex.offset_to_axial(4, 4)
    enemy_hex = start.neighbors()[0]  # E
    enemy_army = _unit(WS, UnitType.INFANTRY, is_army=True)
    board.unit_map[(enemy_hex.q, enemy_hex.r)] = [enemy_army]

    moving_army = _unit(HL, UnitType.INFANTRY, is_army=True)
    moving_leader = _unit(HL, UnitType.GENERAL, is_army=False, is_leader=True)

    target_zoc_hex = None
    for candidate in start.neighbors():
        if candidate == enemy_hex:
            continue
        col, row = candidate.axial_to_offset()
        if not (0 <= col < board.width and 0 <= row < board.height):
            continue
        if board.is_adjacent_to_enemy(candidate, moving_army):
            target_zoc_hex = candidate
            break

    assert target_zoc_hex is not None
    assert board.is_adjacent_to_enemy(start, moving_army) is True
    assert board.is_adjacent_to_enemy(target_zoc_hex, moving_army) is True

    army_neighbors = board.get_neighbors(start, moving_army)
    leader_neighbors = board.get_neighbors(start, moving_leader)

    assert target_zoc_hex not in army_neighbors
    assert target_zoc_hex in leader_neighbors


def test_mountain_hexside_blocks_enemy_adjacency():
    board = Board(width=10, height=10)
    start = Hex.offset_to_axial(4, 4)
    enemy_hex = start.neighbors()[0]
    enemy_army = _unit(WS, UnitType.INFANTRY, is_army=True)
    board.unit_map[(enemy_hex.q, enemy_hex.r)] = [enemy_army]
    board.add_hexside(start.q, start.r, enemy_hex.q, enemy_hex.r, "mountain")

    moving_army = _unit(HL, UnitType.INFANTRY, is_army=True)
    assert board.is_adjacent_to_enemy(start, moving_army) is False


def test_deep_river_hexside_blocks_enemy_adjacency():
    board = Board(width=10, height=10)
    start = Hex.offset_to_axial(4, 4)
    enemy_hex = start.neighbors()[0]
    enemy_army = _unit(WS, UnitType.INFANTRY, is_army=True)
    board.unit_map[(enemy_hex.q, enemy_hex.r)] = [enemy_army]
    board.add_hexside(start.q, start.r, enemy_hex.q, enemy_hex.r, "deep_river")

    moving_army = _unit(HL, UnitType.INFANTRY, is_army=True)
    assert board.is_adjacent_to_enemy(start, moving_army) is False
