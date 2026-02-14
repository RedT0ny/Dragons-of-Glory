from collections import defaultdict

from src.content.constants import HL, WS
from src.content.specs import UnitState, UnitType
from src.game.combat import NavalCombatResolver
from src.game.game_state import GameState
from src.game.map import Hex


class FakeMap:
    def __init__(self):
        self.unit_map = defaultdict(list)

    def get_units_in_hex(self, q, r):
        return self.unit_map.get((q, r), [])

    def add_unit_to_spatial_map(self, unit):
        if not unit.position or unit.position[0] is None or unit.position[1] is None:
            return
        h = Hex.offset_to_axial(*unit.position)
        if unit not in self.unit_map[(h.q, h.r)]:
            self.unit_map[(h.q, h.r)].append(unit)

    def remove_unit_from_spatial_map(self, unit):
        for key, units in list(self.unit_map.items()):
            if unit in units:
                units.remove(unit)
                if not units:
                    del self.unit_map[key]

    def _river_endpoints_local(self, river_hexside):
        if not river_hexside:
            return []
        (q1, r1), (q2, r2) = river_hexside
        return [Hex(q1, r1), Hex(q2, r2)]

    def _fleet_neighbor_states(self, fleet, state):
        return []


class DummyUnit:
    def __init__(
        self,
        *,
        unit_id,
        unit_type,
        allegiance,
        position,
        status=UnitState.ACTIVE,
        combat_rating=0,
        tactical_rating=0,
    ):
        self.id = unit_id
        self.ordinal = 1
        self.unit_type = unit_type
        self.allegiance = allegiance
        self.position = position
        self.status = status
        self.combat_rating = combat_rating
        self.tactical_rating = tactical_rating
        self.passengers = []
        self.transport_host = None
        self.is_transported = False
        self.river_hexside = None

    @property
    def is_on_map(self):
        return self.status in UnitState.on_map_states()

    def is_leader(self):
        return self.unit_type in {
            UnitType.GENERAL,
            UnitType.ADMIRAL,
            UnitType.WIZARD,
            UnitType.HIGHLORD,
            UnitType.HERO,
            UnitType.EMPEROR,
        }

    def is_army(self):
        return self.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY)

    def deplete(self):
        if self.status == UnitState.ACTIVE:
            self.status = UnitState.DEPLETED
        elif self.status == UnitState.DEPLETED:
            self.eliminate()

    def eliminate(self):
        self.status = UnitState.RESERVE
        self.position = (None, None)

    def destroy(self):
        self.status = UnitState.DESTROYED
        self.position = (None, None)


def _fleet(unit_id, allegiance, col, row, *, status=UnitState.ACTIVE, cr=5):
    return DummyUnit(
        unit_id=unit_id,
        unit_type=UnitType.FLEET,
        allegiance=allegiance,
        position=(col, row),
        status=status,
        combat_rating=cr,
    )


def test_naval_combat_is_simultaneous_even_if_both_sink():
    gs = GameState()
    gs.map = FakeMap()
    a = _fleet("a", HL, 4, 4, status=UnitState.DEPLETED, cr=10)
    d = _fleet("d", WS, 5, 4, status=UnitState.DEPLETED, cr=10)
    gs.map.add_unit_to_spatial_map(a)
    gs.map.add_unit_to_spatial_map(d)

    resolver = NavalCombatResolver(gs, [a], [d], roll_d10_fn=lambda: 1, roll_d6_fn=lambda: 6)
    result = resolver.resolve()

    assert result["result"] == "NS/NS"
    assert a.status == UnitState.RESERVE
    assert d.status == UnitState.RESERVE


def test_admiral_or_wizard_tactical_rating_adds_to_fleet_attack():
    gs = GameState()
    gs.map = FakeMap()
    a = _fleet("a", HL, 4, 4, status=UnitState.ACTIVE, cr=1)
    d = _fleet("d", WS, 5, 4, status=UnitState.DEPLETED, cr=1)
    admiral = DummyUnit(
        unit_id="adm",
        unit_type=UnitType.ADMIRAL,
        allegiance=HL,
        position=(4, 4),
        tactical_rating=2,
    )
    a.passengers.append(admiral)
    admiral.transport_host = a
    admiral.is_transported = True
    gs.map.add_unit_to_spatial_map(a)
    gs.map.add_unit_to_spatial_map(d)

    resolver = NavalCombatResolver(gs, [a], [d], roll_d10_fn=lambda: 3, roll_d6_fn=lambda: 6)
    result = resolver.resolve()

    assert result["result"] == "N/NS"
    assert d.status == UnitState.RESERVE


def test_sunk_fleet_sends_ground_passengers_to_reserve():
    gs = GameState()
    gs.map = FakeMap()
    a = _fleet("a", HL, 4, 4, status=UnitState.DEPLETED, cr=1)
    d = _fleet("d", WS, 5, 4, status=UnitState.ACTIVE, cr=10)
    army = DummyUnit(
        unit_id="army",
        unit_type=UnitType.INFANTRY,
        allegiance=HL,
        position=(4, 4),
        status=UnitState.ACTIVE,
        combat_rating=3,
    )
    a.passengers.append(army)
    army.transport_host = a
    army.is_transported = True
    gs.map.add_unit_to_spatial_map(a)
    gs.map.add_unit_to_spatial_map(d)

    resolver = NavalCombatResolver(gs, [a], [d], roll_d10_fn=lambda: 1, roll_d6_fn=lambda: 6)
    resolver.resolve()

    assert a.status == UnitState.RESERVE
    assert army.status == UnitState.RESERVE
    assert army.transport_host is None


def test_wizard_reappears_with_nearest_friendly_stack_when_ship_sinks():
    gs = GameState()
    gs.map = FakeMap()
    sunk = _fleet("sunk", HL, 4, 4, status=UnitState.DEPLETED, cr=1)
    enemy = _fleet("enemy", WS, 5, 4, status=UnitState.ACTIVE, cr=10)
    friendly = _fleet("friendly", HL, 7, 4, status=UnitState.ACTIVE, cr=1)
    wizard = DummyUnit(
        unit_id="wiz",
        unit_type=UnitType.WIZARD,
        allegiance=HL,
        position=(4, 4),
        status=UnitState.ACTIVE,
        tactical_rating=3,
    )
    sunk.passengers.append(wizard)
    wizard.transport_host = sunk
    wizard.is_transported = True
    gs.map.add_unit_to_spatial_map(sunk)
    gs.map.add_unit_to_spatial_map(enemy)
    gs.map.add_unit_to_spatial_map(friendly)

    resolver = NavalCombatResolver(gs, [sunk], [enemy], roll_d10_fn=lambda: 1, roll_d6_fn=lambda: 1)
    resolver.resolve()

    assert sunk.status == UnitState.RESERVE
    assert wizard.status == UnitState.ACTIVE
    assert wizard.position == friendly.position
    assert wizard.transport_host is None
