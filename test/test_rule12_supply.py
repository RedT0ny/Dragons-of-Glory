from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import GamePhase, HexsideType, TerrainType, UnitState, UnitType
from src.game.game_state import GameState
from src.game.map import Board, Hex


def _army(allegiance, col, row, *, status=UnitState.ACTIVE, combat=3, unit_id="army", ordinal=1):
    return SimpleNamespace(
        allegiance=allegiance,
        unit_type=UnitType.INFANTRY,
        status=status,
        combat_rating=combat,
        id=unit_id,
        ordinal=ordinal,
        position=(col, row),
        is_on_map=True,
        is_army=lambda: True,
        is_leader=lambda: False,
    )


def _counter(allegiance, col, row, *, unit_type=UnitType.GENERAL, unit_id="ctr", ordinal=1):
    return SimpleNamespace(
        allegiance=allegiance,
        unit_type=unit_type,
        status=UnitState.ACTIVE,
        combat_rating=0,
        id=unit_id,
        ordinal=ordinal,
        position=(col, row),
        is_on_map=True,
        is_army=lambda: False,
        is_leader=lambda: True,
    )


def _add_unit(board: Board, unit):
    hx = Hex.offset_to_axial(*unit.position)
    board.unit_map[(hx.q, hx.r)].append(unit)


def test_phase_manager_skips_supply_when_standard():
    gs = GameState()
    gs.turn = 5
    gs.phase = GamePhase.COMBAT
    gs.active_player = HL
    gs.initiative_winner = HL
    gs.second_player_has_acted = True
    gs.supply = "standard"
    gs.units = [SimpleNamespace(
        unit_type=UnitType.INFANTRY,
        movement=3,
        movement_points=0,
        attacked_this_turn=True,
        moved_this_turn=True,
        carried_by_citadel_this_turn=True,
        _healed_this_combat_turn=True,
    )]

    gs.phase_manager.advance_phase()

    assert gs.turn == 6
    assert gs.phase == GamePhase.REPLACEMENTS


def test_phase_manager_runs_supply_when_advanced():
    gs = GameState()
    gs.turn = 5
    gs.phase = GamePhase.COMBAT
    gs.active_player = HL
    gs.initiative_winner = HL
    gs.second_player_has_acted = True
    gs.supply = "advanced"
    gs.units = [SimpleNamespace(
        unit_type=UnitType.INFANTRY,
        movement=3,
        movement_points=0,
        attacked_this_turn=True,
        moved_this_turn=True,
        carried_by_citadel_this_turn=True,
        _healed_this_combat_turn=True,
    )]

    called = {"supply": 0}

    def _resolve_supply_phase():
        called["supply"] += 1
        return []

    gs.resolve_supply_phase = _resolve_supply_phase

    gs.phase_manager.advance_phase()
    assert gs.phase == GamePhase.SUPPLY
    assert gs.turn == 5

    gs.phase_manager.advance_phase()
    assert called["supply"] == 1
    assert gs.phase == GamePhase.REPLACEMENTS
    assert gs.turn == 6


def test_supply_no_loss_when_path_exists():
    gs = GameState()
    gs.supply = "advanced"
    gs.active_player = HL
    gs.map = Board(width=5, height=3)

    start = (2, 1)
    loc = (0, 1)
    loc_hex = Hex.offset_to_axial(*loc)
    gs.map.locations[(loc_hex.q, loc_hex.r)] = SimpleNamespace(occupier=HL)

    a1 = _army(HL, *start, combat=2, unit_id="a1")
    a2 = _army(HL, *start, combat=4, unit_id="a2", ordinal=2)
    _add_unit(gs.map, a1)
    _add_unit(gs.map, a2)

    losses = gs.resolve_supply_phase()

    assert losses == []
    assert a1.status == UnitState.ACTIVE
    assert a2.status == UnitState.ACTIVE


def test_supply_blocked_by_enemy_army_causes_loss():
    gs = GameState()
    gs.supply = "advanced"
    gs.active_player = HL
    gs.map = Board(width=3, height=1)

    start = (2, 0)
    loc = (0, 0)
    block = (1, 0)

    loc_hex = Hex.offset_to_axial(*loc)
    block_hex = Hex.offset_to_axial(*block)
    gs.map.locations[(loc_hex.q, loc_hex.r)] = SimpleNamespace(occupier=HL)

    a1 = _army(HL, *start, combat=2, unit_id="a1")
    a2 = _army(HL, *start, combat=5, unit_id="a2", ordinal=2)
    enemy = _army(WS, *block, combat=3, unit_id="e1")
    _add_unit(gs.map, a1)
    _add_unit(gs.map, a2)
    _add_unit(gs.map, enemy)

    losses = gs.resolve_supply_phase()

    assert len(losses) == 1
    assert losses[0].status == UnitState.RESERVE
    assert losses[0].position == (None, None)
    assert losses[0] in (a1, a2)


def test_supply_zoc_requires_friendly_counter():
    # Baseline: path hex in enemy ZOC without friendly counter -> no supply.
    gs = GameState()
    gs.supply = "advanced"
    gs.active_player = HL
    gs.map = Board(width=3, height=2)

    start = (2, 0)
    loc = (0, 0)
    choke = (1, 0)
    enemy_pos = (1, 1)

    for col in range(3):
        row1_hex = Hex.offset_to_axial(col, 1)
        gs.map.grid[(row1_hex.q, row1_hex.r)] = TerrainType.OCEAN.value

    loc_hex = Hex.offset_to_axial(*loc)
    choke_hex = Hex.offset_to_axial(*choke)
    gs.map.locations[(loc_hex.q, loc_hex.r)] = SimpleNamespace(occupier=HL)

    a1 = _army(HL, *start, combat=1, unit_id="a1")
    a2 = _army(HL, *start, combat=2, unit_id="a2", ordinal=2)
    enemy = _army(WS, *enemy_pos, combat=3, unit_id="e1")
    _add_unit(gs.map, a1)
    _add_unit(gs.map, a2)
    _add_unit(gs.map, enemy)

    assert gs.map.is_adjacent_to_enemy(choke_hex, a1) is True
    losses = gs.resolve_supply_phase()
    assert len(losses) == 1

    # With a friendly counter in the ZOC hex, the same path is valid.
    gs2 = GameState()
    gs2.supply = "advanced"
    gs2.active_player = HL
    gs2.map = Board(width=3, height=2)
    for col in range(3):
        row1_hex = Hex.offset_to_axial(col, 1)
        gs2.map.grid[(row1_hex.q, row1_hex.r)] = TerrainType.OCEAN.value
    gs2.map.locations[(loc_hex.q, loc_hex.r)] = SimpleNamespace(occupier=HL)

    b1 = _army(HL, *start, combat=1, unit_id="b1")
    b2 = _army(HL, *start, combat=2, unit_id="b2", ordinal=2)
    e2 = _army(WS, *enemy_pos, combat=3, unit_id="e2")
    friendly_counter = _counter(HL, *choke, unit_id="f1")
    _add_unit(gs2.map, b1)
    _add_unit(gs2.map, b2)
    _add_unit(gs2.map, e2)
    _add_unit(gs2.map, friendly_counter)

    losses2 = gs2.resolve_supply_phase()
    assert losses2 == []


def test_supply_mountain_hexside_blocks_unless_pass():
    gs = GameState()
    gs.supply = "advanced"
    gs.active_player = HL
    gs.map = Board(width=3, height=1)

    start = (2, 0)
    loc = (0, 0)
    mid = (1, 0)

    start_hex = Hex.offset_to_axial(*start)
    mid_hex = Hex.offset_to_axial(*mid)
    loc_hex = Hex.offset_to_axial(*loc)
    gs.map.locations[(loc_hex.q, loc_hex.r)] = SimpleNamespace(occupier=HL)

    gs.map.add_hexside(mid_hex.q, mid_hex.r, loc_hex.q, loc_hex.r, HexsideType.MOUNTAIN.value)

    a1 = _army(HL, *start, combat=1, unit_id="a1")
    a2 = _army(HL, *start, combat=2, unit_id="a2", ordinal=2)
    _add_unit(gs.map, a1)
    _add_unit(gs.map, a2)

    losses = gs.resolve_supply_phase()
    assert len(losses) == 1

    gs2 = GameState()
    gs2.supply = "advanced"
    gs2.active_player = HL
    gs2.map = Board(width=3, height=1)
    gs2.map.locations[(loc_hex.q, loc_hex.r)] = SimpleNamespace(occupier=HL)
    gs2.map.add_hexside(mid_hex.q, mid_hex.r, loc_hex.q, loc_hex.r, HexsideType.PASS.value)
    b1 = _army(HL, *start, combat=1, unit_id="b1")
    b2 = _army(HL, *start, combat=2, unit_id="b2", ordinal=2)
    _add_unit(gs2.map, b1)
    _add_unit(gs2.map, b2)

    losses2 = gs2.resolve_supply_phase()
    assert losses2 == []


def test_supply_attrition_prefers_depleted_army():
    gs = GameState()
    gs.supply = "advanced"
    gs.active_player = HL
    gs.map = Board(width=2, height=1)

    start = (1, 0)
    d = _army(HL, *start, status=UnitState.DEPLETED, combat=4, unit_id="dep")
    a = _army(HL, *start, status=UnitState.ACTIVE, combat=1, unit_id="act", ordinal=2)
    _add_unit(gs.map, d)
    _add_unit(gs.map, a)

    losses = gs.resolve_supply_phase()
    assert len(losses) == 1
    assert losses[0].id == "dep"
    assert d.status == UnitState.RESERVE
    assert a.status == UnitState.ACTIVE
