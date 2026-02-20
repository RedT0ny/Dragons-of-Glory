from types import SimpleNamespace
from unittest.mock import patch

from src.content.constants import HL, WS
from src.content.specs import TerrainType, UnitRace, UnitState, UnitType
from src.game.combat import apply_dragon_orb_bonus
from src.game.game_state import GameState
from src.game.map import Hex


class FakeMap:
    def __init__(self):
        self.unit_map = {}

    def get_units_in_hex(self, q, r):
        return list(self.unit_map.get((q, r), []))

    def add_unit_to_spatial_map(self, unit):
        if not unit.position or unit.position[0] is None or unit.position[1] is None:
            return
        h = Hex.offset_to_axial(*unit.position)
        self.unit_map.setdefault((h.q, h.r), [])
        if unit not in self.unit_map[(h.q, h.r)]:
            self.unit_map[(h.q, h.r)].append(unit)

    def remove_unit_from_spatial_map(self, unit):
        for key, units in list(self.unit_map.items()):
            if unit in units:
                units.remove(unit)
                if not units:
                    del self.unit_map[key]

    def get_terrain(self, _hex_obj):
        return TerrainType.GRASSLAND

    def can_stack_move_to(self, _units, _hex_obj):
        return True


class DummyUnit:
    def __init__(
        self,
        *,
        unit_id,
        allegiance,
        unit_type,
        race,
        position,
        tactical_rating=0,
        is_leader=False,
        is_army=False,
    ):
        self.id = unit_id
        self.ordinal = 1
        self.allegiance = allegiance
        self.unit_type = unit_type
        self.race = race
        self.position = position
        self.status = UnitState.ACTIVE
        self.tactical_rating = tactical_rating
        self._is_leader = is_leader
        self._is_army = is_army
        self.equipment = []

    @property
    def is_on_map(self):
        return self.status in UnitState.on_map_states()

    def is_leader(self):
        return self._is_leader

    def is_army(self):
        return self._is_army

    def destroy(self):
        self.status = UnitState.DESTROYED
        self.position = (None, None)


def _orb(owner, assigned_to):
    asset = SimpleNamespace(id="dragon_orb", owner=owner, assigned_to=assigned_to)

    def _remove_from(unit):
        if asset in unit.equipment:
            unit.equipment.remove(asset)
        asset.assigned_to = None

    asset.remove_from = _remove_from
    return asset


def test_dragon_orb_success_destroys_only_dragons_and_consumes_orb():
    gs = GameState()
    owner = SimpleNamespace(assets={})
    gs.players = {HL: owner, WS: SimpleNamespace(assets={})}

    leader = DummyUnit(
        unit_id="hl_leader",
        allegiance=HL,
        unit_type=UnitType.GENERAL,
        race=UnitRace.HUMAN,
        position=(4, 4),
        tactical_rating=4,
        is_leader=True,
    )
    orb = _orb(owner, leader)
    leader.equipment = [orb]
    owner.assets[orb.id] = orb

    dragon = DummyUnit(
        unit_id="enemy_dragon",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(5, 4),
    )
    draconian = DummyUnit(
        unit_id="enemy_draconian",
        allegiance=WS,
        unit_type=UnitType.INFANTRY,
        race=UnitRace.DRACONIAN,
        position=(5, 4),
        is_army=True,
    )

    logs = apply_dragon_orb_bonus(
        [leader],
        [dragon, draconian],
        consume_asset_fn=gs._consume_asset,
        roll_d6_fn=lambda: 3,
    )

    assert logs
    assert dragon.status == UnitState.DESTROYED
    assert draconian.status == UnitState.ACTIVE
    assert orb not in leader.equipment
    assert "dragon_orb" not in owner.assets


def test_dragon_orb_failure_destroys_leader_and_consumes_orb():
    gs = GameState()
    owner = SimpleNamespace(assets={})
    gs.players = {HL: owner, WS: SimpleNamespace(assets={})}

    leader = DummyUnit(
        unit_id="hl_leader",
        allegiance=HL,
        unit_type=UnitType.GENERAL,
        race=UnitRace.HUMAN,
        position=(4, 4),
        tactical_rating=2,
        is_leader=True,
    )
    orb = _orb(owner, leader)
    leader.equipment = [orb]
    owner.assets[orb.id] = orb

    enemy_dragon = DummyUnit(
        unit_id="enemy_dragon",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(5, 4),
    )

    logs = apply_dragon_orb_bonus(
        [leader],
        [enemy_dragon],
        consume_asset_fn=gs._consume_asset,
        roll_d6_fn=lambda: 6,
    )

    assert logs
    assert leader.status == UnitState.DESTROYED
    assert enemy_dragon.status == UnitState.ACTIVE
    assert orb not in leader.equipment
    assert "dragon_orb" not in owner.assets


def test_resolve_combat_short_circuits_when_orb_clears_defenders():
    gs = GameState()
    gs.map = FakeMap()
    gs.active_player = HL
    gs.players = {HL: SimpleNamespace(assets={}), WS: SimpleNamespace(assets={})}

    attacker = DummyUnit(
        unit_id="hl_army",
        allegiance=HL,
        unit_type=UnitType.INFANTRY,
        race=UnitRace.HUMAN,
        position=(4, 4),
        is_army=True,
    )
    leader = DummyUnit(
        unit_id="hl_leader",
        allegiance=HL,
        unit_type=UnitType.GENERAL,
        race=UnitRace.HUMAN,
        position=(4, 4),
        tactical_rating=6,
        is_leader=True,
    )
    orb = _orb(gs.players[HL], leader)
    leader.equipment = [orb]
    gs.players[HL].assets[orb.id] = orb

    defender_dragon = DummyUnit(
        unit_id="ws_dragon",
        allegiance=WS,
        unit_type=UnitType.WING,
        race=UnitRace.DRAGON,
        position=(5, 4),
    )

    gs.map.add_unit_to_spatial_map(attacker)
    gs.map.add_unit_to_spatial_map(leader)
    gs.map.add_unit_to_spatial_map(defender_dragon)

    target_hex = Hex.offset_to_axial(5, 4)
    with patch("random.randint", return_value=1), patch(
        "src.game.game_state.CombatResolver.resolve",
        side_effect=AssertionError("CRT should not execute when orb clears defenders."),
    ):
        result = gs.resolve_combat([attacker, leader], target_hex)

    assert result["result"] == "-/-"
    assert result["leader_escape_requests"] == []
    assert defender_dragon.status == UnitState.DESTROYED
