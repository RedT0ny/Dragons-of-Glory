from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import HexsideType, LocType, TerrainType, UnitRace, UnitState, UnitType
from src.game.combat import CombatResolver
from src.game.map import Hex


class DummyUnit:
    def __init__(
        self,
        *,
        unit_type,
        allegiance,
        position,
        combat_rating=0,
        tactical_rating=0,
        race=None,
        terrain_affinity=None,
        is_army=False,
        is_leader=False,
    ):
        self.unit_type = unit_type
        self.allegiance = allegiance
        self.position = position
        self.combat_rating = combat_rating
        self.tactical_rating = tactical_rating
        self.race = race
        self.terrain_affinity = terrain_affinity
        self._is_army = is_army
        self._is_leader = is_leader
        self.status = UnitState.ACTIVE

    @property
    def is_on_map(self):
        return self.status in UnitState.on_map_states()

    def is_army(self):
        return self._is_army

    def is_leader(self):
        return self._is_leader

    def deplete(self):
        if self.status == UnitState.ACTIVE:
            self.status = UnitState.DEPLETED
        elif self.status == UnitState.DEPLETED:
            self.eliminate()

    def eliminate(self):
        self.status = UnitState.RESERVE
        self.position = (None, None)


class FakeMap:
    def __init__(self):
        self.terrain = {}
        self.locations = {}
        self.hexsides = {}
        self.ship_bridges = set()

    def get_location(self, hex_obj):
        return self.locations.get((hex_obj.q, hex_obj.r))

    def get_terrain(self, hex_obj):
        return self.terrain.get((hex_obj.q, hex_obj.r), TerrainType.GRASSLAND)

    def get_effective_hexside(self, from_hex, to_hex):
        key = tuple(sorted([(from_hex.q, from_hex.r), (to_hex.q, to_hex.r)]))
        return self.hexsides.get(key)

    def is_ship_bridge(self, from_hex, to_hex, alliance):
        key = tuple(sorted([(from_hex.q, from_hex.r), (to_hex.q, to_hex.r)]))
        return (key, alliance) in self.ship_bridges

    def can_unit_land_on_hex(self, unit, target_hex):
        return True

    def has_enemy_army(self, hex_obj, allegiance):
        return False

    def can_stack_move_to(self, units, hex_obj):
        return True

    def get_movement_cost(self, unit, from_hex, to_hex):
        return 1

    def get_units_in_hex(self, q, r):
        return []

    def is_adjacent_to_enemy(self, hex_obj, unit):
        return False


def _resolver(attackers, defenders, terrain=TerrainType.GRASSLAND, fmap=None):
    game_state = SimpleNamespace(
        map=fmap or FakeMap(),
        move_unit=lambda unit, hex_obj: None,
        is_hex_in_bounds=lambda col, row: True,
    )
    return CombatResolver(attackers, defenders, terrain, game_state=game_state)


def test_drm_leaders_dragons_cavalry_flight_and_affinity():
    fmap = FakeMap()
    atk_hex = Hex.offset_to_axial(4, 4)
    def_hex = Hex.offset_to_axial(5, 4)
    fmap.terrain[(atk_hex.q, atk_hex.r)] = TerrainType.GRASSLAND
    fmap.terrain[(def_hex.q, def_hex.r)] = TerrainType.GRASSLAND

    attackers = [
        DummyUnit(
            unit_type=UnitType.GENERAL,
            allegiance=HL,
            position=(4, 4),
            tactical_rating=2,
            is_leader=True,
        ),
        DummyUnit(
            unit_type=UnitType.WING,
            allegiance=HL,
            position=(4, 4),
            combat_rating=3,
            race=UnitRace.DRAGON,
        ),
        DummyUnit(
            unit_type=UnitType.CAVALRY,
            allegiance=HL,
            position=(4, 4),
            is_army=True,
        ),
        DummyUnit(
            unit_type=UnitType.INFANTRY,
            allegiance=HL,
            position=(4, 4),
            terrain_affinity=TerrainType.GRASSLAND,
            is_army=True,
        ),
    ]
    defenders = [
        DummyUnit(
            unit_type=UnitType.GENERAL,
            allegiance=WS,
            position=(5, 4),
            tactical_rating=1,
            is_leader=True,
        ),
        DummyUnit(
            unit_type=UnitType.WING,
            allegiance=WS,
            position=(5, 4),
            combat_rating=2,
            race=UnitRace.DRAGON,
        ),
        DummyUnit(
            unit_type=UnitType.INFANTRY,
            allegiance=WS,
            position=(5, 4),
            terrain_affinity=TerrainType.GRASSLAND,
            is_army=True,
        ),
    ]

    resolver = _resolver(attackers, defenders, fmap=fmap)
    assert resolver.calculate_total_drm() == 3


def test_drm_location_multiplier_and_location_modifier():
    fmap = FakeMap()
    def_hex = Hex.offset_to_axial(5, 4)
    fmap.locations[(def_hex.q, def_hex.r)] = {"type": LocType.FORTRESS}

    attackers = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=HL, position=(4, 4), is_army=True)]
    defenders = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=WS, position=(5, 4), is_army=True)]

    resolver = _resolver(attackers, defenders, fmap=fmap)
    assert resolver._get_defender_combat_multiplier() == 3
    assert resolver.calculate_total_drm() == -4


def test_drm_crossings_include_deep_river_bridge_ford_and_pass():
    fmap = FakeMap()
    def_hex = Hex.offset_to_axial(5, 5)
    neighbors = def_hex.neighbors()

    for edge_hex, side in [
        (neighbors[0], HexsideType.RIVER),
        (neighbors[1], HexsideType.DEEP_RIVER),
        (neighbors[2], HexsideType.BRIDGE),
        (neighbors[3], HexsideType.FORD),
        (neighbors[4], HexsideType.PASS),
    ]:
        key = tuple(sorted([(edge_hex.q, edge_hex.r), (def_hex.q, def_hex.r)]))
        fmap.hexsides[key] = side

    attackers = []
    for h in neighbors[:5]:
        col, row = h.axial_to_offset()
        attackers.append(
            DummyUnit(
                unit_type=UnitType.INFANTRY,
                allegiance=HL,
                position=(col, row),
                is_army=True,
            )
        )
    defenders = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=WS, position=def_hex.axial_to_offset(), is_army=True)]

    resolver = _resolver(attackers, defenders, fmap=fmap)
    assert resolver.calculate_total_drm() == -13


def test_drm_ship_bridge_counts_as_bridge_crossing():
    fmap = FakeMap()
    atk_hex = Hex.offset_to_axial(4, 4)
    def_hex = Hex.offset_to_axial(5, 4)
    key = tuple(sorted([(atk_hex.q, atk_hex.r), (def_hex.q, def_hex.r)]))
    fmap.ship_bridges.add((key, HL))

    attackers = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=HL, position=(4, 4), is_army=True)]
    defenders = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=WS, position=(5, 4), is_army=True)]

    resolver = _resolver(attackers, defenders, fmap=fmap)
    assert resolver.calculate_total_drm() == -4


def test_drm_cavalry_and_flight_restrictions_apply():
    fmap = FakeMap()
    def_hex = Hex.offset_to_axial(5, 4)
    fmap.locations[(def_hex.q, def_hex.r)] = {"type": LocType.CITY.value}

    attackers = [
        DummyUnit(unit_type=UnitType.CAVALRY, allegiance=HL, position=(4, 4), is_army=True),
        DummyUnit(unit_type=UnitType.WING, allegiance=HL, position=(4, 4)),
    ]
    defenders = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=WS, position=(5, 4), is_army=True)]

    resolver = _resolver(attackers, defenders, fmap=fmap)
    # +1 flight, no cavalry bonus, and city defense modifier -2
    assert resolver.calculate_total_drm() == -1

    fmap.locations[(def_hex.q, def_hex.r)] = {"type": LocType.UNDERCITY.value}
    resolver = _resolver(attackers, defenders, fmap=fmap)
    # no flight bonus in undercity; undercity applies -10
    assert resolver.calculate_total_drm() == -10


def test_defender_in_location_ignores_retreat_result():
    fmap = FakeMap()
    def_hex = Hex.offset_to_axial(5, 4)
    fmap.locations[(def_hex.q, def_hex.r)] = {"type": LocType.CITY.value}

    attackers = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=HL, position=(4, 4), is_army=True)]
    defenders = [DummyUnit(unit_type=UnitType.INFANTRY, allegiance=WS, position=(5, 4), is_army=True)]
    resolver = _resolver(attackers, defenders, fmap=fmap)

    calls = {"count": 0}

    def _count_retreats(_units):
        calls["count"] += 1

    resolver._apply_retreats = _count_retreats
    resolver.apply_results("-/R", defenders, is_attacker=False)
    assert calls["count"] == 0

    fmap.locations[(def_hex.q, def_hex.r)] = None
    resolver = _resolver(attackers, defenders, fmap=fmap)
    resolver._apply_retreats = _count_retreats
    resolver.apply_results("-/R", defenders, is_attacker=False)
    assert calls["count"] == 1
