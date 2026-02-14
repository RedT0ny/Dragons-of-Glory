from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitType, UnitState
from src.game.game_state import GameState
from src.game.map import Board, Hex


def _unit(unit_id, allegiance, unit_type, pos):
    return SimpleNamespace(
        id=unit_id,
        allegiance=allegiance,
        unit_type=unit_type,
        race=None,
        land=None,
        position=pos,
        status=UnitState.ACTIVE,
        movement=4,
        movement_points=4,
        terrain_affinity=None,
        moved_this_turn=False,
        attacked_this_turn=False,
        is_transported=False,
        transport_host=None,
        passengers=[],
        river_hexside=None,
        is_on_map=True,
        is_army=lambda: unit_type in (UnitType.INFANTRY, UnitType.CAVALRY),
        is_leader=lambda: unit_type in (UnitType.GENERAL, UnitType.ADMIRAL, UnitType.HERO, UnitType.WIZARD, UnitType.HIGHLORD, UnitType.EMPEROR),
    )


def test_undo_last_movement_restores_unit_position_and_mp():
    gs = GameState()
    gs.map = Board(width=10, height=10)
    gs.phase = GamePhase.MOVEMENT
    gs.active_player = HL
    gs.turn = 3

    unit = _unit("u1", HL, UnitType.INFANTRY, (2, 2))
    gs.units = [unit]
    gs.map.add_unit_to_spatial_map(unit)

    gs.push_movement_undo_snapshot()

    target = Hex.offset_to_axial(3, 2)
    gs.move_unit(unit, target)

    assert unit.position == (3, 2)
    assert unit.moved_this_turn is True

    assert gs.undo_last_movement() is True
    assert unit.position == (2, 2)
    assert unit.movement_points == 4
    assert unit.moved_this_turn is False
    start_hex = Hex.offset_to_axial(2, 2)
    restored = gs.map.get_units_in_hex(start_hex.q, start_hex.r)
    assert unit in restored


def test_undo_rejected_if_turn_or_player_changed():
    gs = GameState()
    gs.map = Board(width=10, height=10)
    gs.phase = GamePhase.MOVEMENT
    gs.active_player = HL
    gs.turn = 1

    unit = _unit("u1", HL, UnitType.INFANTRY, (2, 2))
    gs.units = [unit]
    gs.push_movement_undo_snapshot()

    gs.active_player = WS
    assert gs.undo_last_movement() is False
    assert gs.can_undo_movement() is False


def test_undo_restores_transport_links_and_spatial_map():
    gs = GameState()
    gs.map = Board(width=10, height=10)
    gs.phase = GamePhase.MOVEMENT
    gs.active_player = HL
    gs.turn = 2

    fleet = _unit("fleet", HL, UnitType.FLEET, (4, 4))
    army = _unit("army", HL, UnitType.INFANTRY, (4, 4))
    gs.units = [fleet, army]
    gs.map.add_unit_to_spatial_map(fleet)
    gs.map.add_unit_to_spatial_map(army)

    gs.push_movement_undo_snapshot()

    fleet.passengers.append(army)
    army.transport_host = fleet
    army.is_transported = True
    gs.map.remove_unit_from_spatial_map(army)

    assert gs.undo_last_movement() is True
    assert army.transport_host is None
    assert army.is_transported is False
    assert army in gs.map.get_units_in_hex(Hex.offset_to_axial(4, 4).q, Hex.offset_to_axial(4, 4).r)
