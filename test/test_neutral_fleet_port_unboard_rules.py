from types import SimpleNamespace

from src.content.constants import HL, NEUTRAL
from src.content.specs import UnitType
from src.game.game_state import GameState
from src.game.map import Board, Hex


def _fleet(col, row, allegiance=HL):
    return SimpleNamespace(
        id=f"fleet_{col}_{row}",
        unit_type=UnitType.FLEET,
        allegiance=allegiance,
        movement=4,
        movement_points=4,
        position=(col, row),
        river_hexside=None,
        moved_this_turn=False,
        is_on_map=True,
        passengers=[],
        is_army=lambda: False,
        is_leader=lambda: False,
    )


def _army(col, row, allegiance=HL):
    return SimpleNamespace(
        id=f"army_{col}_{row}",
        unit_type=UnitType.INFANTRY,
        allegiance=allegiance,
        movement=4,
        movement_points=4,
        position=(col, row),
        moved_this_turn=False,
        is_on_map=True,
        is_transported=True,
        transport_host=None,
        race=None,
        is_army=lambda: True,
        is_leader=lambda: False,
    )


def test_fleet_cannot_enter_port_of_neutral_country():
    board = Board(width=8, height=8)
    board.populate_terrain({"2,2": "ocean"})
    target_hex = Hex.offset_to_axial(3, 2)
    board.locations[(target_hex.q, target_hex.r)] = SimpleNamespace(
        loc_type="port",
        country_id="neutral_land",
        occupier=NEUTRAL,
        is_capital=False,
    )
    fleet = _fleet(2, 2)
    start_hex = Hex.offset_to_axial(2, 2)

    _, cost = board.find_fleet_route(fleet, start_hex, target_hex)
    assert cost == float("inf")


def test_fleet_can_enter_stateless_neutral_port():
    board = Board(width=8, height=8)
    board.populate_terrain({"2,2": "ocean"})
    target_hex = Hex.offset_to_axial(3, 2)
    board.locations[(target_hex.q, target_hex.r)] = SimpleNamespace(
        loc_type="port",
        country_id=None,
        occupier=NEUTRAL,
        is_capital=False,
    )
    fleet = _fleet(2, 2)
    start_hex = Hex.offset_to_axial(2, 2)

    _, cost = board.find_fleet_route(fleet, start_hex, target_hex)
    assert cost == 1


def test_fleet_cannot_unboard_into_neutral_country_coastal_hex():
    gs = GameState()
    gs.map = Board(width=8, height=8)
    gs.map.populate_terrain({"3,2": "c_grassland"})
    gs.countries = {
        "neutral_land": SimpleNamespace(
            id="neutral_land",
            allegiance=NEUTRAL,
            territories={(3, 2)},
        )
    }

    carrier = _fleet(3, 2)
    passenger = _army(3, 2)
    passenger.transport_host = carrier
    carrier.passengers = [passenger]
    gs.units = [carrier, passenger]

    ok = gs.unboard_unit(passenger, Hex.offset_to_axial(3, 2))
    assert ok is False


def test_fleet_can_unboard_into_stateless_neutral_port():
    gs = GameState()
    gs.map = Board(width=8, height=8)
    target_hex = Hex.offset_to_axial(3, 2)
    gs.map.locations[(target_hex.q, target_hex.r)] = SimpleNamespace(
        loc_type="port",
        country_id=None,
        occupier=NEUTRAL,
        is_capital=False,
    )
    gs.countries = {}

    carrier = _fleet(3, 2)
    passenger = _army(3, 2)
    passenger.transport_host = carrier
    carrier.passengers = [passenger]
    gs.units = [carrier, passenger]

    ok = gs.unboard_unit(passenger, target_hex)
    assert ok is True
    assert passenger.transport_host is None
    assert passenger.is_transported is False
