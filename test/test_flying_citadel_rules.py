from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import GamePhase, LocType, TerrainType, UnitState, UnitType
from src.game.combat import CombatResolver
from src.game.game_state import GameState
from src.game.map import Board, Hex


class DummyUnit:
    def __init__(
        self,
        *,
        unit_id,
        unit_type,
        allegiance,
        position,
        combat_rating=0,
        tactical_rating=0,
        is_army=False,
        is_leader=False,
    ):
        self.id = unit_id
        self.ordinal = 1
        self.unit_type = unit_type
        self.allegiance = allegiance
        self.position = position
        self.combat_rating = combat_rating
        self.tactical_rating = tactical_rating
        self._is_army = is_army
        self._is_leader = is_leader
        self.status = UnitState.ACTIVE
        self.movement = 4
        self.movement_points = 4
        self.moved_this_turn = False
        self.attacked_this_turn = False
        self.transport_host = None
        self.is_transported = False
        self.carried_by_citadel_this_turn = False
        self.terrain_affinity = None
        self.race = None
        self.passengers = []
        self.equipment = []

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

    def destroy(self):
        self.status = UnitState.DESTROYED
        self.position = (None, None)


def test_citadel_ignores_terrain_and_hexside_for_movement():
    board = Board(width=8, height=8)
    start = Hex.offset_to_axial(2, 2)
    target = Hex.offset_to_axial(3, 2)
    board.grid[(target.q, target.r)] = TerrainType.OCEAN.value
    board.add_hexside(start.q, start.r, target.q, target.r, "sea")

    citadel = DummyUnit(
        unit_id="citadel_1",
        unit_type=UnitType.CITADEL,
        allegiance=HL,
        position=(2, 2),
    )

    assert board.can_unit_land_on_hex(citadel, target) is True
    assert board.get_movement_cost(citadel, start, target) == 1


def test_boarding_citadel_requires_army_not_moved_this_turn():
    gs = GameState()
    gs.map = SimpleNamespace(remove_unit_from_spatial_map=lambda unit: None)

    citadel = DummyUnit(
        unit_id="citadel_1",
        unit_type=UnitType.CITADEL,
        allegiance=HL,
        position=(4, 4),
    )
    army = DummyUnit(
        unit_id="inf_1",
        unit_type=UnitType.INFANTRY,
        allegiance=HL,
        position=(4, 4),
        is_army=True,
    )
    army.moved_this_turn = True

    citadel.can_carry = lambda unit: True
    citadel.load_unit = lambda unit: citadel.passengers.append(unit)

    assert gs.board_unit(citadel, army) is False


def test_army_carried_by_citadel_cannot_move_independently_same_turn():
    gs = GameState()
    gs.map = Board(width=8, height=8)
    gs.phase = GamePhase.MOVEMENT

    citadel = DummyUnit(
        unit_id="citadel_1",
        unit_type=UnitType.CITADEL,
        allegiance=HL,
        position=(2, 2),
    )
    passenger = DummyUnit(
        unit_id="inf_1",
        unit_type=UnitType.INFANTRY,
        allegiance=HL,
        position=(2, 2),
        is_army=True,
    )
    passenger.transport_host = citadel
    passenger.is_transported = True
    citadel.passengers.append(passenger)

    gs.units = [citadel, passenger]
    gs.map.add_unit_to_spatial_map(citadel)

    target = Hex.offset_to_axial(3, 2)
    gs.move_unit(citadel, target)
    assert passenger.carried_by_citadel_this_turn is True

    assert gs.unboard_unit(passenger) is True
    unboarded_pos = passenger.position
    gs.move_unit(passenger, Hex.offset_to_axial(4, 2))
    assert passenger.position == unboarded_pos


def test_ws_ground_only_attack_on_citadel_is_blocked():
    gs = GameState()
    gs.map = Board(width=8, height=8)
    gs.active_player = WS

    defender_hex = Hex.offset_to_axial(4, 4)
    ws_ground = DummyUnit(
        unit_id="ws_inf",
        unit_type=UnitType.INFANTRY,
        allegiance=WS,
        position=(3, 4),
        combat_rating=3,
        is_army=True,
    )
    hl_citadel = DummyUnit(
        unit_id="hl_citadel",
        unit_type=UnitType.CITADEL,
        allegiance=HL,
        position=(4, 4),
        combat_rating=4,
    )
    gs.map.add_unit_to_spatial_map(ws_ground)
    gs.map.add_unit_to_spatial_map(hl_citadel)

    result = gs.resolve_combat([ws_ground], defender_hex)
    assert result["result"] == "-/-"


def test_air_attack_against_citadel_gets_fortified_city_bonus():
    fmap = SimpleNamespace(
        get_location=lambda hex_obj: None,
        get_terrain=lambda hex_obj: TerrainType.GRASSLAND,
        get_effective_hexside=lambda from_hex, to_hex: None,
        is_ship_bridge=lambda from_hex, to_hex, alliance: False,
        can_unit_land_on_hex=lambda unit, target_hex: True,
        has_enemy_army=lambda hex_obj, allegiance: False,
        can_stack_move_to=lambda units, hex_obj: True,
        get_movement_cost=lambda unit, from_hex, to_hex: 1,
        get_units_in_hex=lambda q, r: [],
        is_adjacent_to_enemy=lambda hex_obj, unit: False,
    )
    gs = SimpleNamespace(
        map=fmap,
        move_unit=lambda unit, hex_obj: None,
        is_hex_in_bounds=lambda col, row: True,
    )

    attackers = [DummyUnit(unit_id="ws_wing", unit_type=UnitType.WING, allegiance=WS, position=(3, 4), combat_rating=3)]
    defenders = [DummyUnit(unit_id="hl_citadel", unit_type=UnitType.CITADEL, allegiance=HL, position=(4, 4), combat_rating=4)]

    resolver = CombatResolver(attackers, defenders, TerrainType.GRASSLAND, game_state=gs)
    assert resolver._get_defender_combat_multiplier() == 2
    assert resolver.calculate_total_drm() == -2


def test_citadel_attack_removes_ws_location_bonus():
    fmap = SimpleNamespace(
        get_location=lambda hex_obj: {"type": LocType.FORTRESS.value},
        get_terrain=lambda hex_obj: TerrainType.MOUNTAIN,
        get_effective_hexside=lambda from_hex, to_hex: None,
        is_ship_bridge=lambda from_hex, to_hex, alliance: False,
        can_unit_land_on_hex=lambda unit, target_hex: True,
        has_enemy_army=lambda hex_obj, allegiance: False,
        can_stack_move_to=lambda units, hex_obj: True,
        get_movement_cost=lambda unit, from_hex, to_hex: 1,
        get_units_in_hex=lambda q, r: [],
        is_adjacent_to_enemy=lambda hex_obj, unit: False,
    )
    gs = SimpleNamespace(
        map=fmap,
        move_unit=lambda unit, hex_obj: None,
        is_hex_in_bounds=lambda col, row: True,
    )

    attackers = [DummyUnit(unit_id="hl_citadel", unit_type=UnitType.CITADEL, allegiance=HL, position=(3, 4), combat_rating=4)]
    defenders = [DummyUnit(unit_id="ws_inf", unit_type=UnitType.INFANTRY, allegiance=WS, position=(4, 4), combat_rating=3, is_army=True)]

    resolver = CombatResolver(attackers, defenders, TerrainType.MOUNTAIN, game_state=gs)
    assert resolver._get_defender_combat_multiplier() == 1
    assert resolver._get_defender_location() is None
