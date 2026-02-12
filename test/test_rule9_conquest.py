from types import SimpleNamespace

from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import CountrySpec, LocationSpec, UnitState, UnitType, GamePhase
from src.game.country import Country
from src.game.deployment import DeploymentService
from src.game.game_state import GameState
from src.game.map import Hex


class FakeMap:
    def __init__(self):
        self.units_by_hex = {}
        self.locations = {}

    def get_units_in_hex(self, q, r):
        return self.units_by_hex.get((q, r), [])

    def remove_unit_from_spatial_map(self, unit):
        for key, units in self.units_by_hex.items():
            if unit in units:
                units.remove(unit)

    def can_unit_land_on_hex(self, unit, target_hex):
        return True

    def can_stack_move_to(self, moving_units, target_hex):
        return True

    def is_coastal(self, hex_obj):
        return False

    def get_location(self, hex_obj):
        return self.locations.get((hex_obj.q, hex_obj.r))


class FakeUnit:
    def __init__(self, land, allegiance, unit_type, status=UnitState.ACTIVE, position=None, is_leader=False):
        self.land = land
        self.allegiance = allegiance
        self.unit_type = unit_type
        self.status = status
        self.position = position
        self._is_leader = is_leader

    @property
    def is_on_map(self):
        return self.status in UnitState.on_map_states()

    def is_army(self):
        return self.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY)

    def is_leader(self):
        return self._is_leader

    def destroy(self):
        self.status = UnitState.DESTROYED
        self.position = (None, None)


def _country(country_id, allegiance, coords=(0, 0), tags=None):
    spec = CountrySpec(
        id=country_id,
        capital_id=f"{country_id}_cap",
        strength=10,
        allegiance=allegiance,
        alignment=(0, 0),
        color="#000000",
        locations=[LocationSpec(id=f"{country_id}_cap", loc_type="city", coords=coords, is_capital=True)],
        territories=[coords],
        tags=list(tags or []),
    )
    return Country(spec)


def _register_country_locations(gs: GameState, country: Country):
    for loc in country.locations.values():
        h = Hex.offset_to_axial(*loc.coords)
        gs.map.locations[(h.q, h.r)] = {"country_id": country.id, "location_id": loc.id, "occupier": None, "type": "city"}


def test_standard_conquest_destroys_armies_wings_and_leaders_but_not_fleets():
    gs = GameState()
    gs.map = FakeMap()
    ws_country = _country("qualinesti", WS, coords=(5, 5))
    gs.countries = {"qualinesti": ws_country}
    _register_country_locations(gs, ws_country)

    loc_hex = Hex.offset_to_axial(5, 5)
    enemy_army = FakeUnit("enemy", HL, UnitType.INFANTRY, UnitState.ACTIVE, (5, 5))
    gs.map.units_by_hex[(loc_hex.q, loc_hex.r)] = [enemy_army]

    ws_army = FakeUnit("qualinesti", WS, UnitType.INFANTRY, UnitState.ACTIVE, (4, 5))
    ws_wing = FakeUnit("qualinesti", WS, UnitType.WING, UnitState.ACTIVE, (4, 6))
    ws_leader = FakeUnit("qualinesti", WS, UnitType.GENERAL, UnitState.ACTIVE, (4, 4), is_leader=True)
    ws_fleet = FakeUnit("qualinesti", WS, UnitType.FLEET, UnitState.ACTIVE, (3, 5))
    gs.units = [ws_army, ws_wing, ws_leader, ws_fleet]

    gs.resolve_end_of_combat_conquest()

    assert ws_country.conquered is True
    assert ws_country.locations[f"{ws_country.id}_cap"].occupier == HL
    assert ws_army.status == UnitState.DESTROYED
    assert ws_wing.status == UnitState.DESTROYED
    assert ws_leader.status == UnitState.DESTROYED
    assert ws_fleet.status == UnitState.ACTIVE


def test_location_is_liberated_when_enemy_army_no_longer_occupies_it():
    gs = GameState()
    gs.map = FakeMap()
    ws_country = _country("ergoth", WS, coords=(6, 6))
    gs.countries = {"ergoth": ws_country}
    _register_country_locations(gs, ws_country)

    loc = ws_country.locations[f"{ws_country.id}_cap"]
    loc.occupier = HL
    gs.resolve_end_of_combat_conquest()

    assert loc.occupier is None


def test_solamnic_group_conquest_is_pooled_for_ws():
    gs = GameState()
    gs.map = FakeMap()
    tag = gs.tag_knight_countries

    coast = _country("coastlund", WS, coords=(1, 1), tags=[tag])
    sancrist = _country("sancrist", WS, coords=(2, 2), tags=[tag])
    tower = _country("tower", WS, coords=(3, 3), tags=[tag])
    gs.countries = {"coastlund": coast, "sancrist": sancrist, "tower": tower}

    for c in gs.countries.values():
        _register_country_locations(gs, c)
        h = Hex.offset_to_axial(*next(iter(c.locations.values())).coords)
        gs.map.units_by_hex[(h.q, h.r)] = [FakeUnit("hl", HL, UnitType.INFANTRY, UnitState.ACTIVE, h.axial_to_offset())]

    coast_army = FakeUnit("coastlund", WS, UnitType.INFANTRY, UnitState.ACTIVE, (0, 0))
    tower_army = FakeUnit("tower", WS, UnitType.INFANTRY, UnitState.ACTIVE, (0, 1))
    gs.units = [coast_army, tower_army]

    gs.resolve_end_of_combat_conquest()

    assert coast.conquered is True
    assert sancrist.conquered is True
    assert tower.conquered is True
    assert coast_army.status == UnitState.DESTROYED
    assert tower_army.status == UnitState.DESTROYED


def test_replacements_respect_conquered_locations_and_allow_conqueror_use():
    gs = GameState()
    gs.map = FakeMap()
    gs.phase = GamePhase.REPLACEMENTS
    gs.active_player = WS
    gs.players = {WS: SimpleNamespace(spec=SimpleNamespace(country_deployment=False))}
    service = DeploymentService(gs)

    ws_country = _country("solamnia", WS, coords=(8, 8))
    ws_country.locations["fort"] = SimpleNamespace(id="fort", loc_type="fortress", coords=(9, 9), occupier=HL, is_capital=False)
    gs.countries = {"solamnia": ws_country}
    _register_country_locations(gs, ws_country)

    ws_unit = FakeUnit("solamnia", WS, UnitType.INFANTRY, UnitState.READY, (None, None))
    ws_hexes = service.get_valid_deployment_hexes(ws_unit, allow_territory_wide=False)
    assert (8, 8) in ws_hexes
    assert (9, 9) not in ws_hexes

    gs.active_player = HL
    gs.players[HL] = SimpleNamespace(spec=SimpleNamespace(country_deployment=False))
    hl_stateless = FakeUnit(None, HL, UnitType.INFANTRY, UnitState.READY, (None, None))
    hl_hexes = service.get_valid_deployment_hexes(hl_stateless, allow_territory_wide=False)
    assert (9, 9) in hl_hexes
