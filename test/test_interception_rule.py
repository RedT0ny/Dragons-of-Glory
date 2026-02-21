from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitRace, UnitState, UnitType
from src.game.game_state import GameState
from src.game.map import Board, Hex
from src.game.movement import MovementService


class DummyUnit:
    def __init__(
        self,
        *,
        unit_id,
        allegiance,
        unit_type,
        race,
        position,
        movement=8,
        dragonflight=None,
    ):
        self.id = unit_id
        self.ordinal = 1
        self.allegiance = allegiance
        self.unit_type = unit_type
        self.race = race
        self.position = position
        self.status = UnitState.ACTIVE
        self.movement = movement
        self.movement_points = movement
        self.moved_this_turn = False
        self.attacked_this_turn = False
        self.transport_host = None
        self.is_transported = False
        self.carried_by_citadel_this_turn = False
        self.river_hexside = None
        self.passengers = []
        self.equipment = []
        self.spec = type("Spec", (), {"dragonflight": dragonflight})

    @property
    def is_on_map(self):
        return self.status in UnitState.on_map_states()

    def is_army(self):
        return self.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY)

    def is_leader(self):
        return self.unit_type in {
            UnitType.GENERAL,
            UnitType.ADMIRAL,
            UnitType.HERO,
            UnitType.WIZARD,
            UnitType.HIGHLORD,
            UnitType.EMPEROR,
        }

    def deplete(self):
        if self.status == UnitState.ACTIVE:
            self.status = UnitState.DEPLETED
        elif self.status == UnitState.DEPLETED:
            self.destroy()

    def eliminate(self):
        self.status = UnitState.RESERVE
        self.position = (None, None)

    def destroy(self):
        self.status = UnitState.DESTROYED
        self.position = (None, None)


def _setup_state():
    gs = GameState()
    gs.map = Board(width=20, height=20)
    gs.phase = GamePhase.MOVEMENT
    gs.active_player = HL
    return gs


def test_interception_success_forces_attack_and_interceptor_returns(monkeypatch):
    gs = _setup_state()
    mover = DummyUnit(
        unit_id="hl_wing",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(2, 2),
        movement=8,
    )
    interceptor = DummyUnit(
        unit_id="ws_wing",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(7, 2),
        movement=8,
    )
    gs.units = [mover, interceptor]
    gs.map.add_unit_to_spatial_map(mover)
    gs.map.add_unit_to_spatial_map(interceptor)
    service = MovementService(gs)

    calls = {"count": 0}

    def fake_resolve_combat(attackers, target_hex, **kwargs):
        calls["count"] += 1
        assert attackers and attackers[0] is interceptor
        assert target_hex == Hex.offset_to_axial(*mover.position)
        return {"result": "-/-", "leader_escape_requests": [], "advance_available": False}

    gs.resolve_combat = fake_resolve_combat
    monkeypatch.setattr("src.game.movement.random.random", lambda: 0.0)
    monkeypatch.setattr("src.game.movement.random.randint", lambda a, b: 6)
    monkeypatch.setattr("src.game.movement.random.choice", lambda seq: seq[0])

    target = Hex.offset_to_axial(5, 2)
    result = service.move_units_to_hex([mover], target)

    assert result.errors == []
    assert calls["count"] >= 1
    assert mover.position == (5, 2)
    assert interceptor.position == (7, 2)


def test_interception_failed_attempt_allows_normal_movement(monkeypatch):
    gs = _setup_state()
    mover = DummyUnit(
        unit_id="hl_wing",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(2, 2),
        movement=8,
    )
    interceptor = DummyUnit(
        unit_id="ws_wing",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(7, 2),
        movement=8,
    )
    gs.units = [mover, interceptor]
    gs.map.add_unit_to_spatial_map(mover)
    gs.map.add_unit_to_spatial_map(interceptor)
    service = MovementService(gs)

    calls = {"count": 0}

    def fake_resolve_combat(*args, **kwargs):
        calls["count"] += 1
        return {"result": "-/-", "leader_escape_requests": [], "advance_available": False}

    gs.resolve_combat = fake_resolve_combat
    monkeypatch.setattr("src.game.movement.random.random", lambda: 0.0)
    monkeypatch.setattr("src.game.movement.random.randint", lambda a, b: 1)
    monkeypatch.setattr("src.game.movement.random.choice", lambda seq: seq[0])

    target = Hex.offset_to_axial(5, 2)
    result = service.move_units_to_hex([mover], target)

    assert result.errors == []
    assert calls["count"] == 0
    assert mover.position == (5, 2)
    assert interceptor.position == (7, 2)


def test_successful_interception_combat_can_stop_mover(monkeypatch):
    gs = _setup_state()
    mover = DummyUnit(
        unit_id="hl_wing",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(2, 2),
        movement=8,
    )
    interceptor = DummyUnit(
        unit_id="ws_wing",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(7, 2),
        movement=8,
    )
    gs.units = [mover, interceptor]
    gs.map.add_unit_to_spatial_map(mover)
    gs.map.add_unit_to_spatial_map(interceptor)
    service = MovementService(gs)

    def fake_resolve_combat(attackers, target_hex, **kwargs):
        for unit in gs.map.get_units_in_hex(target_hex.q, target_hex.r):
            if unit.allegiance == HL and unit.unit_type == UnitType.WING:
                unit.destroy()
        return {"result": "E/-", "leader_escape_requests": [], "advance_available": False}

    gs.resolve_combat = fake_resolve_combat
    monkeypatch.setattr("src.game.movement.random.random", lambda: 0.0)
    monkeypatch.setattr("src.game.movement.random.randint", lambda a, b: 6)
    monkeypatch.setattr("src.game.movement.random.choice", lambda seq: seq[0])

    target = Hex.offset_to_axial(5, 2)
    result = service.move_units_to_hex([mover], target)

    assert result.errors == []
    assert not mover.is_on_map
    assert mover.position == (None, None)
    assert interceptor.position == (7, 2)


def test_fleet_cannot_intercept_enemy_wing():
    gs = _setup_state()
    service = MovementService(gs)
    fleet = DummyUnit(
        unit_id="ws_fleet",
        allegiance=WS,
        unit_type=UnitType.FLEET,
        race=UnitRace.HUMAN,
        position=(8, 2),
    )
    mover_wing = DummyUnit(
        unit_id="hl_wing",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(2, 2),
    )
    assert service._can_unit_intercept_target(fleet, [mover_wing]) is False


def test_same_interceptor_attempts_only_once_per_opponent_movement_step(monkeypatch):
    gs = _setup_state()
    mover = DummyUnit(
        unit_id="hl_wing",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(2, 2),
        movement=8,
    )
    interceptor = DummyUnit(
        unit_id="ws_wing",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(7, 2),
        movement=8,
    )
    gs.units = [mover, interceptor]
    gs.map.add_unit_to_spatial_map(mover)
    gs.map.add_unit_to_spatial_map(interceptor)
    service = MovementService(gs)

    attempts = {"count": 0}

    def fake_randint(a, b):
        attempts["count"] += 1
        return 1

    monkeypatch.setattr("src.game.movement.random.random", lambda: 0.0)
    monkeypatch.setattr("src.game.movement.random.randint", fake_randint)
    monkeypatch.setattr("src.game.movement.random.choice", lambda seq: seq[0])

    target = Hex.offset_to_axial(5, 2)
    result = service.move_units_to_hex([mover], target)

    assert result.errors == []
    assert mover.position == (5, 2)
    assert attempts["count"] == 1


def test_stacked_interceptors_attack_together(monkeypatch):
    gs = _setup_state()
    mover = DummyUnit(
        unit_id="hl_wing",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(2, 2),
        movement=8,
    )
    interceptor_a = DummyUnit(
        unit_id="ws_wing_a",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(7, 2),
        movement=8,
    )
    interceptor_b = DummyUnit(
        unit_id="ws_wing_b",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(7, 2),
        movement=8,
    )
    gs.units = [mover, interceptor_a, interceptor_b]
    gs.map.add_unit_to_spatial_map(mover)
    gs.map.add_unit_to_spatial_map(interceptor_a)
    gs.map.add_unit_to_spatial_map(interceptor_b)
    service = MovementService(gs)

    calls = {"count": 0}

    def fake_resolve_combat(attackers, target_hex, **kwargs):
        calls["count"] += 1
        assert len(attackers) == 2
        return {"result": "-/-", "leader_escape_requests": [], "advance_available": False}

    gs.resolve_combat = fake_resolve_combat
    monkeypatch.setattr("src.game.movement.random.random", lambda: 0.0)
    monkeypatch.setattr("src.game.movement.random.randint", lambda a, b: 6)
    monkeypatch.setattr("src.game.movement.random.choice", lambda seq: seq[0])

    target = Hex.offset_to_axial(5, 2)
    result = service.move_units_to_hex([mover], target)
    assert result.errors == []
    assert calls["count"] >= 1
    assert interceptor_a.position == (7, 2)
    assert interceptor_b.position == (7, 2)


def test_hl_dragon_interceptor_requires_valid_commander():
    gs = _setup_state()
    service = MovementService(gs)
    mover = DummyUnit(
        unit_id="ws_wing",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.PEGASUS,
        position=(2, 2),
    )
    dragon = DummyUnit(
        unit_id="hl_red_dragon",
        allegiance=HL,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(5, 2),
        dragonflight="red",
    )
    assert service._dragon_interceptor_has_required_commander(dragon) is False

    leader = DummyUnit(
        unit_id="hl_red_lord",
        allegiance=HL,
        unit_type=UnitType.HIGHLORD,
        race=UnitRace.HUMAN,
        position=(5, 2),
        dragonflight="red",
    )
    dragon.passengers = [leader]
    assert service._dragon_interceptor_has_required_commander(dragon) is True
    assert service._can_unit_intercept_target(dragon, [mover]) is True


def test_ws_dragon_interceptor_requires_elf_or_solamnic_commander():
    service = MovementService(_setup_state())
    dragon = DummyUnit(
        unit_id="ws_dragon",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(5, 2),
    )
    assert service._dragon_interceptor_has_required_commander(dragon) is False

    leader = DummyUnit(
        unit_id="ws_elf_leader",
        allegiance=WS,
        unit_type=UnitType.GENERAL,
        race=UnitRace.ELF,
        position=(5, 2),
    )
    dragon.passengers = [leader]
    assert service._dragon_interceptor_has_required_commander(dragon) is True
