from types import SimpleNamespace

from src.content.constants import HL
from src.content.specs import UnitRace, UnitState, UnitType
from src.game.ai_baseline import TacticalPlanner
from src.game.game_state import GameState
from src.game.map import Hex
from src.game.movement import MovementService


class FakeMap:
    def __init__(self):
        self.removed = []
        self.unit_map = {}

    def remove_unit_from_spatial_map(self, unit):
        self.removed.append(unit)

    def get_units_in_hex(self, q, r):
        return self.unit_map.get((q, r), [])


class DummyCarrier:
    def __init__(self, *, moved_this_turn):
        self.unit_type = UnitType.WING
        self.position = (5, 5)
        self.moved_this_turn = moved_this_turn
        self.passengers = []
        self.id = "wing_1"
        self.movement = 18
        self.movement_points = 18
        self.transport_host = None

    def can_carry(self, unit):
        return True

    def load_unit(self, unit):
        self.passengers.append(unit)

    def is_fleet(self):
        return False


class DummyUnit:
    def __init__(self):
        self.position = (5, 5)
        self.is_transported = False
        self.transport_host = None
        self.id = "inf_1"


def test_wing_that_already_moved_cannot_board_unit():
    gs = GameState()
    gs.map = FakeMap()
    movement_service = MovementService(gs)
    wing = DummyCarrier(moved_this_turn=True)
    army = DummyUnit()

    ok = movement_service.board_unit(wing, army)

    assert ok is False
    assert army.is_transported is False
    assert army.transport_host is None
    assert army not in gs.map.removed


def test_wing_can_board_when_not_moved():
    gs = GameState()
    gs.map = FakeMap()
    movement_service = MovementService(gs)
    wing = DummyCarrier(moved_this_turn=False)
    army = DummyUnit()

    ok = movement_service.board_unit(wing, army)

    assert ok is True
    assert army.is_transported is True
    assert army.transport_host is wing
    assert army in gs.map.removed


class DummyDragonWing(DummyCarrier):
    def __init__(self, unit_id, flight, position):
        super().__init__(moved_this_turn=False)
        self.id = unit_id
        self.ordinal = 1
        self.allegiance = HL
        self.race = UnitRace.DRAGON
        self.status = UnitState.ACTIVE
        self.position = position
        self.spec = SimpleNamespace(dragonflight=flight)

    @property
    def is_on_map(self):
        return True

    def is_wing(self):
        return True

    def is_dragon(self):
        return True

    def is_leader(self):
        return False

    def can_carry(self, unit):
        if not unit.is_leader() or len(self.passengers) >= 1:
            return False
        if unit.unit_type not in (UnitType.HIGHLORD, UnitType.EMPEROR):
            return False
        return unit.spec.dragonflight is None or unit.spec.dragonflight == self.spec.dragonflight


class DummyHighlord:
    def __init__(self, unit_id, flight, position):
        self.id = unit_id
        self.ordinal = 1
        self.allegiance = HL
        self.unit_type = UnitType.HIGHLORD
        self.status = UnitState.ACTIVE
        self.position = position
        self.spec = SimpleNamespace(dragonflight=flight)
        self.is_transported = False
        self.transport_host = None
        self.moved_this_turn = False
        self.movement_points = 10

    @property
    def is_on_map(self):
        return True

    def is_leader(self):
        return True

    def is_wing(self):
        return False

    def is_dragon(self):
        return False


def test_ai_boards_all_same_hex_dragon_commanders_before_movement():
    gs = GameState()
    gs.map = FakeMap()
    green_wing = DummyDragonWing("green_dragon_wing_2", "green", (36, 23))
    red_wing = DummyDragonWing("red_dragon_wing_1", "red", (34, 23))
    hullek = DummyHighlord("hullek", "green", (36, 23))
    verminaard = DummyHighlord("verminaard", "red", (34, 23))
    green_hex = Hex.offset_to_axial(36, 23)
    red_hex = Hex.offset_to_axial(34, 23)
    gs.map.unit_map = {
        (green_hex.q, green_hex.r): [green_wing, hullek],
        (red_hex.q, red_hex.r): [red_wing, verminaard],
    }
    ctx = SimpleNamespace(
        side=HL,
        friendly_units=[green_wing, red_wing, hullek, verminaard],
        game_state=gs,
        movement_service=MovementService(gs),
    )

    boarded = TacticalPlanner()._board_dragon_commanders(ctx)

    assert boarded is True
    assert hullek.transport_host is green_wing
    assert verminaard.transport_host is red_wing
    assert green_wing.passengers == [hullek]
    assert red_wing.passengers == [verminaard]
