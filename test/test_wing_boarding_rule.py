from types import SimpleNamespace

from src.content.specs import UnitType
from src.game.game_state import GameState


class FakeMap:
    def __init__(self):
        self.removed = []

    def remove_unit_from_spatial_map(self, unit):
        self.removed.append(unit)


class DummyCarrier:
    def __init__(self, *, moved_this_turn):
        self.unit_type = UnitType.WING
        self.position = (5, 5)
        self.moved_this_turn = moved_this_turn
        self.passengers = []
        self.id = "wing_1"
        self.movement = 18
        self.movement_points = 18

    def can_carry(self, unit):
        return True

    def load_unit(self, unit):
        self.passengers.append(unit)


class DummyUnit:
    def __init__(self):
        self.position = (5, 5)
        self.is_transported = False
        self.transport_host = None
        self.id = "inf_1"


def test_wing_that_already_moved_cannot_board_unit():
    gs = GameState()
    gs.map = FakeMap()
    wing = DummyCarrier(moved_this_turn=True)
    army = DummyUnit()

    ok = gs.board_unit(wing, army)

    assert ok is False
    assert army.is_transported is False
    assert army.transport_host is None
    assert army not in gs.map.removed


def test_wing_can_board_when_not_moved():
    gs = GameState()
    gs.map = FakeMap()
    wing = DummyCarrier(moved_this_turn=False)
    army = DummyUnit()

    ok = gs.board_unit(wing, army)

    assert ok is True
    assert army.is_transported is True
    assert army.transport_host is wing
    assert army in gs.map.removed
