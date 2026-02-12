from types import SimpleNamespace

from src.content.constants import HL, NEUTRAL, WS
from src.content.specs import UnitState
from src.game.game_state import GameState


KNIGHT_TAG = "knight_countries"


def _country(country_id: str, allegiance: str = NEUTRAL, tags=None):
    return SimpleNamespace(id=country_id, allegiance=allegiance, tags=list(tags or []))


def _unit(land: str):
    return SimpleNamespace(land=land, status=UnitState.INACTIVE, allegiance=NEUTRAL)


def test_ws_solamnic_bonus_counts_hl_controlled_countries():
    gs = GameState()
    gs.countries = {
        "coastlund": _country("coastlund", HL, [KNIGHT_TAG]),
        "hinterlund": _country("hinterlund", NEUTRAL, [KNIGHT_TAG]),
        "sancrist": _country("sancrist", HL, [KNIGHT_TAG]),
        "solanthus": _country("solanthus", WS, [KNIGHT_TAG]),
        "southlund": _country("southlund", NEUTRAL, [KNIGHT_TAG]),
    }

    assert gs.get_ws_solamnic_activation_bonus() == 2


def test_first_solamnic_activation_also_activates_tower_for_ws():
    gs = GameState()
    gs.countries = {
        "coastlund": _country("coastlund", NEUTRAL, [KNIGHT_TAG]),
        "hinterlund": _country("hinterlund", NEUTRAL, [KNIGHT_TAG]),
        "sancrist": _country("sancrist", NEUTRAL, [KNIGHT_TAG]),
        "solanthus": _country("solanthus", NEUTRAL, [KNIGHT_TAG]),
        "southlund": _country("southlund", NEUTRAL, [KNIGHT_TAG]),
        "tower": _country("tower", NEUTRAL, [KNIGHT_TAG]),
    }
    gs.units = [_unit("coastlund"), _unit("tower")]

    gs.activate_country("coastlund", HL)

    assert gs.countries["coastlund"].allegiance == HL
    assert gs.countries["tower"].allegiance == WS
    assert gs.units[0].status == UnitState.READY
    assert gs.units[1].status == UnitState.READY
    assert gs.units[1].allegiance == WS


def test_tower_not_auto_activated_if_not_first_solamnic_activation():
    gs = GameState()
    gs.countries = {
        "coastlund": _country("coastlund", HL, [KNIGHT_TAG]),
        "hinterlund": _country("hinterlund", NEUTRAL, [KNIGHT_TAG]),
        "sancrist": _country("sancrist", NEUTRAL, [KNIGHT_TAG]),
        "solanthus": _country("solanthus", NEUTRAL, [KNIGHT_TAG]),
        "southlund": _country("southlund", NEUTRAL, [KNIGHT_TAG]),
        "tower": _country("tower", NEUTRAL, [KNIGHT_TAG]),
    }

    gs.activate_country("hinterlund", HL)

    assert gs.countries["tower"].allegiance == NEUTRAL
