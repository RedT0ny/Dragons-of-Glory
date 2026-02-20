from types import SimpleNamespace

from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import AssetSpec, TerrainType, UnitSpec, UnitState, UnitType
from src.game.combat import CombatResolver, apply_gnome_tech_bonus
from src.game.diplomacy import DiplomacyActivationService
from src.game.event import Asset
from src.game.game_state import GameState
from src.game.map import Board, Hex
from src.game.unit import Army, Leader


def _army_spec(*, unit_id="army", allegiance=HL, combat=10, tactical=1, movement=4):
    return UnitSpec(
        id=unit_id,
        unit_type=UnitType.INFANTRY.value,
        race="human",
        country="testland",
        dragonflight=None,
        allegiance=allegiance,
        terrain_affinity=None,
        combat_rating=combat,
        tactical_rating=tactical,
        movement=movement,
    )


def _leader_spec(*, unit_id="leader", allegiance=HL):
    return UnitSpec(
        id=unit_id,
        unit_type=UnitType.GENERAL.value,
        race="human",
        country="testland",
        dragonflight=None,
        allegiance=allegiance,
        terrain_affinity=None,
        combat_rating=2,
        tactical_rating=2,
        movement=3,
    )


def _asset(asset_id, bonus, *, is_consumable=False, requirements=None):
    spec = AssetSpec(
        id=asset_id,
        asset_type="artifact",
        description=asset_id,
        effect="",
        bonus=bonus,
        requirements=requirements or [],
        is_consumable=is_consumable,
    )
    return Asset(spec)


def test_numeric_bonuses_apply_additive_and_multiplier():
    army = Army(_army_spec())
    army.status = UnitState.ACTIVE

    army.equipment = [SimpleNamespace(bonus={"combat_rating": 2})]
    assert army.combat_rating == 12

    army.equipment = [SimpleNamespace(bonus={"combat_rating": "x2"})]
    assert army.combat_rating == 20

    army.equipment = [SimpleNamespace(bonus={"tactical_rating": "x3"})]
    assert army.tactical_rating == 3

    army.equipment = [SimpleNamespace(bonus={"movement": "x2"})]
    assert army.movement == 8


def test_terrain_affinity_bonus_is_applied_from_artifact():
    army = Army(_army_spec())
    army.equipment = [SimpleNamespace(bonus={"terrain_affinity": "jungle"})]
    assert army.terrain_affinity == TerrainType.JUNGLE


def test_emperor_bonus_overrides_leader_unit_type():
    leader = Leader(_leader_spec())
    leader.status = UnitState.ACTIVE
    leader.position = (1, 1)

    crown = _asset(
        "crown_of_power",
        {"other": "emperor"},
        requirements=[{"type": "unit_type", "value": "leader"}],
    )
    crown.apply_to(leader)
    assert leader.unit_type == UnitType.EMPEROR

    crown.remove_from(leader)
    assert leader.unit_type == UnitType.GENERAL


def test_country_diplomacy_bonus_affects_activation_target_rating():
    gs = GameState()
    gs.active_player = HL
    gs.countries = {
        "thorbardin": SimpleNamespace(id="thorbardin", allegiance=NEUTRAL, alignment=(2, 4))
    }
    leader = Leader(_leader_spec(allegiance=HL))
    leader.status = UnitState.ACTIVE
    leader.position = (2, 2)

    hammer = _asset("hammer", {"diplomacy": ["kaolyn", "thorbardin"]})
    owner = SimpleNamespace(assets={hammer.id: hammer})
    hammer.owner = owner
    hammer.assigned_to = leader
    leader.equipment.append(hammer)
    gs.units = [leader]

    assert gs.get_country_activation_bonus(HL, "thorbardin") == 1

    service = DiplomacyActivationService(gs)
    attempt = service.build_activation_attempt("thorbardin")
    assert attempt is not None
    assert attempt.target_rating == 5

    leader.status = UnitState.DESTROYED
    assert gs.get_country_activation_bonus(HL, "thorbardin") == 0


def test_gnome_tech_bonus_non_double_and_doubles_cases():
    attacker = SimpleNamespace(
        id="atk_army",
        allegiance=HL,
        unit_type=UnitType.INFANTRY,
        is_on_map=True,
        equipment=[SimpleNamespace(id="gnome_tech", bonus={"other": "gnome_tech"}, is_consumable=True)],
        is_army=lambda: True,
    )
    defender = SimpleNamespace(
        id="def_army",
        allegiance=WS,
        unit_type=UnitType.INFANTRY,
        is_on_map=True,
        equipment=[SimpleNamespace(id="gnome_tech", bonus={"other": "gnome_tech"}, is_consumable=True)],
        is_army=lambda: True,
    )

    consumed = []
    rolls = iter([5, 2, 3, 3])
    bonuses, _ = apply_gnome_tech_bonus(
        [attacker],
        [defender],
        consume_asset_fn=lambda asset, unit: consumed.append((asset.id, unit.id)),
        decide_use_fn=lambda _u, _s: True,
        roll_d6_fn=lambda: next(rolls),
    )

    assert bonuses["attacker"] == 5
    assert bonuses["defender"] == 6
    assert ("gnome_tech", "def_army") in consumed


def test_dragon_slayer_and_armor_modify_drm():
    fmap = SimpleNamespace(
        get_location=lambda hex_obj: None,
        get_terrain=lambda hex_obj: TerrainType.FOREST,
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

    attackers = [
        SimpleNamespace(
            id="dragon_wing",
            unit_type=UnitType.WING,
            race="dragon",
            allegiance=HL,
            position=(3, 3),
            combat_rating=4,
            tactical_rating=0,
            equipment=[],
            is_on_map=True,
            is_army=lambda: False,
            is_leader=lambda: False,
        )
    ]
    defenders = [
        SimpleNamespace(
            id="def_army",
            unit_type=UnitType.INFANTRY,
            race="human",
            allegiance=WS,
            position=(4, 3),
            combat_rating=4,
            tactical_rating=0,
            equipment=[SimpleNamespace(bonus={"other": "dragon_slayer"}), SimpleNamespace(bonus={"other": "armor"})],
            is_on_map=True,
            is_army=lambda: True,
            is_leader=lambda: False,
        )
    ]
    resolver = CombatResolver(attackers, defenders, TerrainType.FOREST, game_state=gs)
    assert resolver.calculate_total_drm() == -1


def test_healing_and_revive_other_bonuses():
    gs = GameState()
    gs.map = Board(width=8, height=8)

    army = Army(_army_spec(unit_id="army_heal"))
    army.status = UnitState.DEPLETED
    army.position = (2, 2)
    healing = _asset("medallion", {"other": "healing"}, is_consumable=True)
    owner_hl = SimpleNamespace(assets={healing.id: healing})
    healing.owner = owner_hl
    healing.assigned_to = army
    army.equipment.append(healing)

    logs = gs._apply_combat_healing([army])
    assert army.status == UnitState.ACTIVE
    assert getattr(army, "_healed_this_combat_turn", False) is True
    assert "medallion" not in owner_hl.assets
    assert any("Healing activated" in msg for msg in logs)

    leader = Leader(_leader_spec(unit_id="revive_leader"))
    leader.allegiance = HL
    leader.status = UnitState.DESTROYED
    leader.position = (None, None)
    revive = _asset("blue_crystal_staff", {"other": "revive"}, is_consumable=True)
    owner_hl.assets[revive.id] = revive
    revive.owner = owner_hl
    revive.assigned_to = leader
    leader.equipment.append(revive)

    friendly_army = Army(_army_spec(unit_id="friendly_stack", allegiance=HL))
    friendly_army.status = UnitState.ACTIVE
    friendly_army.position = (4, 4)
    gs.map.add_unit_to_spatial_map(friendly_army)

    origin = Hex.offset_to_axial(3, 4)
    requests = gs._resolve_leader_revives([leader], {leader: origin})
    assert requests
    assert leader.status == UnitState.ACTIVE
    assert leader.position == (None, None)
    assert requests[0].leader is leader
    assert "blue_crystal_staff" not in owner_hl.assets
