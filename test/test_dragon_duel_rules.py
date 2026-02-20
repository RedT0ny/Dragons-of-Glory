from src.content.constants import HL, WS
from src.content.specs import UnitRace, UnitState, UnitType
from src.game.combat import DragonDuelResolver
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
        status=UnitState.ACTIVE,
        combat_rating=0,
        race=None,
        tactical_rating=0,
        dragonflight=None,
        is_army=False,
        is_leader=False,
    ):
        self.id = unit_id
        self.ordinal = 1
        self.unit_type = unit_type
        self.allegiance = allegiance
        self.position = position
        self.status = status
        self.combat_rating = combat_rating
        self.race = race
        self.tactical_rating = tactical_rating
        self.passengers = []
        self.transport_host = None
        self.is_transported = False
        self.attacked_this_turn = False
        self.moved_this_turn = False
        self._is_army = is_army
        self._is_leader = is_leader
        self.spec = type("Spec", (), {"dragonflight": dragonflight})

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


def _unit(**kwargs):
    return DummyUnit(**kwargs)


def test_dragon_duel_hits_are_simultaneous():
    gs = GameState()
    gs.map = Board(width=12, height=12)

    atk = _unit(
        unit_id="hl_dragon",
        unit_type=UnitType.WING,
        allegiance=HL,
        position=(4, 4),
        status=UnitState.DEPLETED,
        combat_rating=1,
        race=UnitRace.DRAGON,
    )
    dfn = _unit(
        unit_id="ws_dragon",
        unit_type=UnitType.WING,
        allegiance=WS,
        position=(5, 4),
        status=UnitState.DEPLETED,
        combat_rating=1,
        race=UnitRace.DRAGON,
    )
    gs.map.add_unit_to_spatial_map(atk)
    gs.map.add_unit_to_spatial_map(dfn)

    duel = DragonDuelResolver(gs, [atk], [dfn], roll_d6_fn=lambda: 4)
    outcome = duel.resolve()

    assert outcome["rounds"] == 1
    assert atk.status == UnitState.DESTROYED
    assert dfn.status == UnitState.DESTROYED


def test_unled_dragon_cannot_attack_non_dragon_stack():
    gs = GameState()
    dragon = _unit(
        unit_id="hl_dragon",
        unit_type=UnitType.WING,
        allegiance=HL,
        position=(4, 4),
        combat_rating=3,
        race=UnitRace.DRAGON,
    )
    defender = _unit(
        unit_id="ws_inf",
        unit_type=UnitType.INFANTRY,
        allegiance=WS,
        position=(5, 4),
        combat_rating=2,
        race=UnitRace.HUMAN,
        is_army=True,
    )
    assert gs.can_units_attack_stack([dragon], [defender]) is False


def test_hl_dragon_with_matching_highlord_can_attack_non_dragon_stack():
    gs = GameState()
    dragon = _unit(
        unit_id="hl_red_dragon",
        unit_type=UnitType.WING,
        allegiance=HL,
        position=(4, 4),
        combat_rating=3,
        race=UnitRace.DRAGON,
        dragonflight="red",
    )
    leader = _unit(
        unit_id="hl_red_lord",
        unit_type=UnitType.HIGHLORD,
        allegiance=HL,
        position=(4, 4),
        race=UnitRace.HUMAN,
        is_leader=True,
        dragonflight="red",
    )
    defender = _unit(
        unit_id="ws_inf",
        unit_type=UnitType.INFANTRY,
        allegiance=WS,
        position=(5, 4),
        combat_rating=2,
        race=UnitRace.HUMAN,
        is_army=True,
    )
    assert gs.can_units_attack_stack([dragon, leader], [defender]) is True


def test_all_highlords_destroyed_blocks_hl_dragon_ground_attack():
    gs = GameState()
    dragon = _unit(
        unit_id="hl_dragon",
        unit_type=UnitType.WING,
        allegiance=HL,
        position=(4, 4),
        combat_rating=3,
        race=UnitRace.DRAGON,
        dragonflight="blue",
    )
    emperor = _unit(
        unit_id="hl_emperor",
        unit_type=UnitType.EMPEROR,
        allegiance=HL,
        position=(4, 4),
        is_leader=True,
    )
    dragon.passengers.append(emperor)
    dead_highlord = _unit(
        unit_id="hl_lord_1",
        unit_type=UnitType.HIGHLORD,
        allegiance=HL,
        position=(None, None),
        status=UnitState.DESTROYED,
        is_leader=True,
        dragonflight="blue",
    )
    gs.units = [dragon, emperor, dead_highlord]
    defender = _unit(
        unit_id="ws_inf",
        unit_type=UnitType.INFANTRY,
        allegiance=WS,
        position=(5, 4),
        combat_rating=2,
        race=UnitRace.HUMAN,
        is_army=True,
    )
    assert gs.can_units_attack_stack([dragon], [defender]) is False


def test_emperor_destruction_promotes_random_highlord():
    gs = GameState()
    gs.map = Board(width=10, height=10)

    emperor = _unit(
        unit_id="emperor",
        unit_type=UnitType.EMPEROR,
        allegiance=HL,
        position=(None, None),
        status=UnitState.DESTROYED,
        is_leader=True,
    )
    candidate = _unit(
        unit_id="candidate_highlord",
        unit_type=UnitType.HIGHLORD,
        allegiance=HL,
        position=(3, 3),
        status=UnitState.ACTIVE,
        is_leader=True,
    )
    gs.units = [emperor, candidate]
    gs._cleanup_destroyed_units([emperor])
    assert getattr(candidate, "_unit_type_override", None) == UnitType.EMPEROR
