from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import TerrainType, UnitState, UnitType
from src.game.combat import CombatResolver, CombatService
from src.game.map import Board, Hex
from src.game.movement import MovementService


def _set_terrain(board: Board, col: int, row: int, terrain: str):
    hex_obj = Hex.offset_to_axial(col, row)
    board.grid[(hex_obj.q, hex_obj.r)] = terrain


def _wing_unit():
    unit = SimpleNamespace(
        id="wing_1",
        unit_type=UnitType.WING,
        allegiance=HL,
        movement=4,
        movement_points=4,
        position=(2, 2),
        status=UnitState.ACTIVE,
        ordinal=None,
    )
    unit.is_wing = lambda: True
    unit.is_army = lambda: False
    unit.is_fleet = lambda: False
    unit.is_citadel = lambda: False
    unit.is_leader = lambda: False
    return unit


def _combat_unit(unit_id, unit_type, allegiance, position):
    def is_army():
        return unit_type in (UnitType.INFANTRY, UnitType.CAVALRY)

    def is_wing():
        return unit_type == UnitType.WING

    unit = SimpleNamespace(
        id=unit_id,
        unit_type=unit_type,
        allegiance=allegiance,
        movement=4,
        movement_points=4,
        position=position,
        status=UnitState.ACTIVE,
        transport_host=None,
        is_on_map=True,
        is_army=is_army,
        is_wing=is_wing,
        is_fleet=lambda: False,
        is_citadel=lambda: False,
        is_leader=lambda: False,
        is_combat_unit=lambda: is_army() or is_wing(),
    )
    return unit


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
        get_terrain=lambda hex_obj: TerrainType.OCEAN,
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
        get_country_by_hex=lambda col, row: None,
    )
    wing = _wing_unit()

    service = CombatService(game_state)

    valid = service._get_valid_retreat_hexes(wing, start)

    assert ocean_neighbor not in valid
    assert land_neighbor in valid


def test_blocked_crt_retreat_eliminates_unit():
    unit = _combat_unit("cavalry_1", UnitType.CAVALRY, WS, (4, 4))
    damage_calls = []
    fake_map = SimpleNamespace()
    game_state = SimpleNamespace(
        map=fake_map,
        units=[],
        players={},
        active_player=HL,
        movement_service=SimpleNamespace(normalize_transport_state=lambda: None),
        damage_unit=lambda damaged, mode=None: (
            damage_calls.append((damaged, mode)),
            setattr(damaged, "status", UnitState.DESTROYED),
        ),
    )
    service = CombatService(game_state)
    service._get_valid_retreat_hexes = lambda unit_arg, start_hex: []

    service._retreat_single_unit(unit)

    assert damage_calls == [(unit, "eliminate")]
    assert unit.status == UnitState.DESTROYED


def test_blocked_src_cavalry_stays_to_fight():
    attacker = _combat_unit("infantry_1", UnitType.INFANTRY, HL, (3, 4))
    defender = _combat_unit("cavalry_1", UnitType.CAVALRY, WS, (4, 4))
    target_hex = Hex.offset_to_axial(4, 4)
    fake_map = SimpleNamespace(get_location=lambda hex_obj: None)
    game_state = SimpleNamespace(
        map=fake_map,
        units=[],
        players={},
        active_player=HL,
        movement_service=SimpleNamespace(normalize_transport_state=lambda: None),
    )
    service = CombatService(game_state)
    service._get_valid_retreat_hexes = lambda unit_arg, start_hex: []

    result = service._apply_precombat_special_retreat([attacker], [defender], target_hex)

    assert result["applied"] is True
    assert result["result"] == "-/SRC"
    assert defender.status == UnitState.ACTIVE
    assert defender.position == (4, 4)


def test_blocked_srw_wing_stays_to_fight():
    attacker = _combat_unit("cavalry_1", UnitType.CAVALRY, HL, (3, 4))
    defender = _combat_unit("wing_1", UnitType.WING, WS, (4, 4))
    target_hex = Hex.offset_to_axial(4, 4)
    fake_map = SimpleNamespace(get_location=lambda hex_obj: None)
    game_state = SimpleNamespace(
        map=fake_map,
        units=[],
        players={},
        active_player=HL,
        movement_service=SimpleNamespace(normalize_transport_state=lambda: None),
    )
    service = CombatService(game_state)
    service._get_valid_retreat_hexes = lambda unit_arg, start_hex: []

    result = service._apply_precombat_special_retreat([attacker], [defender], target_hex)

    assert result["applied"] is True
    assert result["result"] == "-/SRW"
    assert defender.status == UnitState.ACTIVE
    assert defender.position == (4, 4)


def _leader_unit(unit_id, allegiance, position):
    unit = SimpleNamespace(
        id=unit_id,
        unit_type=UnitType.HERO,
        allegiance=allegiance,
        movement=4,
        movement_points=4,
        position=position,
        status=UnitState.ACTIVE,
        transport_host=None,
        is_on_map=True,
        is_army=lambda: False,
        is_wing=lambda: False,
        is_fleet=lambda: False,
        is_citadel=lambda: False,
        is_leader=lambda: True,
        is_combat_unit=lambda: False,
    )
    return unit


def test_leader_riding_with_wing_retreats_only_one_hex():
    attacker = _combat_unit("infantry_1", UnitType.INFANTRY, HL, (3, 4))
    wing = _combat_unit("wing_1", UnitType.WING, WS, (4, 4))
    leader = _leader_unit("leader_1", WS, (4, 4))
    target_hex = Hex.offset_to_axial(4, 4)

    moves = []
    def move_unit(unit, hex_obj):
        unit.position = hex_obj.axial_to_offset()
        moves.append((unit.id, unit.position))

    fake_map = SimpleNamespace(
        get_location=lambda hex_obj: None,
        can_unit_land_on_hex=lambda unit, hex_obj: True,
        can_stack_move_to=lambda units, hex_obj: True,
        has_enemy_army=lambda hex_obj, allegiance: False,
    )
    game_state = SimpleNamespace(
        map=fake_map,
        units=[],
        players={},
        active_player=HL,
        movement_service=SimpleNamespace(normalize_transport_state=lambda: None),
        damage_unit=lambda damaged, mode=None: None,
        get_units_at=lambda hex_obj: [wing, leader],
        move_unit=move_unit,
    )
    service = CombatService(game_state)
    service._get_valid_retreat_hexes = lambda unit_arg, start_hex: [start_hex.neighbors()[0]]

    result = service._apply_precombat_special_retreat([attacker], [wing, leader], target_hex)

    assert result["applied"] is True
    assert wing.position == leader.position
    origin = Hex.offset_to_axial(4, 4)
    final = Hex.offset_to_axial(*leader.position)
    assert origin.distance_to(final) == 1
    assert len(moves) == 2  # wing + leader, leader must not be retreated a second hex


def test_leaders_only_stack_is_not_retreated_by_special_retreat():
    # Leaders-only stacks never reach this path in real combat: attackers that
    # get here always contain a control unit, which triggers the leader-stack
    # escape before the special retreat. Leaders are therefore never retreated
    # directly here — only carried by a wing/cavalry.
    attacker = _combat_unit("infantry_1", UnitType.INFANTRY, HL, (3, 4))
    leader_a = _leader_unit("leader_a", WS, (4, 4))
    leader_b = _leader_unit("leader_b", WS, (4, 4))
    target_hex = Hex.offset_to_axial(4, 4)

    moves = []
    def move_unit(unit, hex_obj):
        unit.position = hex_obj.axial_to_offset()
        moves.append((unit.id, unit.position))

    fake_map = SimpleNamespace(
        get_location=lambda hex_obj: None,
        can_unit_land_on_hex=lambda unit, hex_obj: True,
        can_stack_move_to=lambda units, hex_obj: True,
        has_enemy_army=lambda hex_obj, allegiance: False,
    )
    game_state = SimpleNamespace(
        map=fake_map,
        units=[],
        players={},
        active_player=HL,
        movement_service=SimpleNamespace(normalize_transport_state=lambda: None),
        damage_unit=lambda damaged, mode=None: None,
        get_units_at=lambda hex_obj: [leader_a, leader_b],
        move_unit=move_unit,
    )
    service = CombatService(game_state)
    service._get_valid_retreat_hexes = lambda unit_arg, start_hex: [start_hex.neighbors()[0]]

    result = service._apply_precombat_special_retreat([attacker], [leader_a, leader_b], target_hex)

    assert result["applied"] is True
    assert moves == []
    assert leader_a.position == (4, 4)
    assert leader_b.position == (4, 4)
