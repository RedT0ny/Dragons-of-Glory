from types import SimpleNamespace

from src.content.constants import HL, NEUTRAL, WS
from src.content.specs import UnitState, UnitType
from src.game.game_state import GameState


class FakeMap:
    def remove_unit_from_spatial_map(self, unit):
        return None


def _unit(
    *,
    land,
    allegiance=HL,
    unit_type=UnitType.INFANTRY,
    status=UnitState.RESERVE,
    dragonflight=None,
):
    return SimpleNamespace(
        id=f"{land}_{unit_type.value}",
        land=land,
        allegiance=allegiance,
        unit_type=unit_type,
        status=status,
        position=(None, None),
        spec=SimpleNamespace(dragonflight=dragonflight),
        is_army=lambda: unit_type in (UnitType.INFANTRY, UnitType.CAVALRY),
        is_leader=lambda: unit_type in (UnitType.GENERAL, UnitType.ADMIRAL, UnitType.HERO, UnitType.HIGHLORD, UnitType.EMPEROR, UnitType.WIZARD),
        destroy=lambda: None,
    )


def _country(country_id, allegiance=NEUTRAL, conquered=False, tags=None):
    return SimpleNamespace(id=country_id, allegiance=allegiance, conquered=conquered, tags=list(tags or []))


def test_conscription_pair_does_not_mix_army_and_fleet():
    gs = GameState()
    army = _unit(land="icewall", unit_type=UnitType.INFANTRY)
    fleet = _unit(land="icewall", unit_type=UnitType.FLEET)

    assert gs.can_conscript_pair(army, fleet) is False


def test_army_pair_allows_same_dragonflight():
    gs = GameState()
    a1 = _unit(land="land_a", unit_type=UnitType.INFANTRY, dragonflight="red")
    a2 = _unit(land="land_b", unit_type=UnitType.CAVALRY, dragonflight="red")

    assert gs.can_conscript_pair(a1, a2) is True


def test_fleet_conscription_is_delayed_until_next_replacements_turn():
    gs = GameState()
    gs.turn = 3
    kept = _unit(land="icewall", unit_type=UnitType.FLEET, status=UnitState.RESERVE)
    discarded = _unit(land="icewall", unit_type=UnitType.FLEET, status=UnitState.RESERVE)
    gs.units = [kept, discarded]

    gs.apply_conscription(kept, discarded)

    assert kept.status == UnitState.INACTIVE
    assert kept.replacement_ready_turn == 4
    assert discarded.status == UnitState.DESTROYED

    gs.process_delayed_fleet_replacements()
    assert kept.status == UnitState.INACTIVE

    gs.turn = 4
    gs.process_delayed_fleet_replacements()
    assert kept.status == UnitState.READY
    assert not hasattr(kept, "replacement_ready_turn")


def test_country_conquest_destroys_non_map_fleets_but_keeps_active_fleets():
    gs = GameState()
    gs.map = FakeMap()
    country = _country("qualinesti", WS, conquered=False)
    gs.countries = {"qualinesti": country}

    reserve_fleet = _unit(land="qualinesti", allegiance=WS, unit_type=UnitType.FLEET, status=UnitState.RESERVE)
    active_fleet = _unit(land="qualinesti", allegiance=WS, unit_type=UnitType.FLEET, status=UnitState.ACTIVE)

    def destroy_reserve():
        reserve_fleet.status = UnitState.DESTROYED
        reserve_fleet.position = (None, None)

    reserve_fleet.destroy = destroy_reserve

    gs.units = [reserve_fleet, active_fleet]
    gs._destroy_country_upon_conquest(country)

    assert country.conquered is True
    assert reserve_fleet.status == UnitState.DESTROYED
    assert active_fleet.status == UnitState.ACTIVE


def test_conquered_non_knight_reserve_fleet_is_destroyed():
    gs = GameState()
    gs.map = FakeMap()
    gs.countries = {"icewall": _country("icewall", WS, conquered=True)}
    fleet = _unit(land="icewall", allegiance=WS, unit_type=UnitType.FLEET, status=UnitState.RESERVE)

    def destroy_fleet():
        fleet.status = UnitState.DESTROYED
        fleet.position = (None, None)

    fleet.destroy = destroy_fleet
    gs.units = [fleet]

    gs._enforce_conquered_fleet_replacement_rule()

    assert fleet.status == UnitState.DESTROYED


def test_conquered_knight_reserve_fleet_survives_if_any_knight_unconquered():
    gs = GameState()
    gs.map = FakeMap()
    tag = gs.tag_knight_countries
    gs.countries = {
        "tower": _country("tower", WS, conquered=True, tags=[tag]),
        "coastlund": _country("coastlund", WS, conquered=False, tags=[tag]),
    }
    fleet = _unit(land="tower", allegiance=WS, unit_type=UnitType.FLEET, status=UnitState.RESERVE)

    def destroy_fleet():
        fleet.status = UnitState.DESTROYED
        fleet.position = (None, None)

    fleet.destroy = destroy_fleet
    gs.units = [fleet]

    gs._enforce_conquered_fleet_replacement_rule()

    assert fleet.status == UnitState.RESERVE
