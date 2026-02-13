from types import SimpleNamespace
from unittest.mock import patch

from src.content.constants import HL, NEUTRAL, WS
from src.game.diplomacy import DiplomacyActivationService


def _country(country_id: str, allegiance: str, alignment: tuple[int, int], tags=None):
    return SimpleNamespace(
        id=country_id,
        allegiance=allegiance,
        alignment=alignment,
        tags=list(tags or []),
    )


def _game_state(active_player, countries, solamnic_bonus=0, solamnic_enabled=False):
    activated = []

    def _activate(country_id, allegiance):
        activated.append((country_id, allegiance))

    state = SimpleNamespace(
        active_player=active_player,
        countries=countries,
        is_solamnic_country_for_tower_rule=lambda country_id: solamnic_enabled and country_id == "coastlund",
        get_ws_solamnic_activation_bonus=lambda: solamnic_bonus,
        activate_country=_activate,
    )
    state.activated = activated
    return state


def test_build_activation_attempt_uses_ws_rating_and_solamnic_bonus_for_ws():
    gs = _game_state(
        active_player=WS,
        countries={"coastlund": _country("coastlund", NEUTRAL, (3, 7), tags=["knight_countries"])},
        solamnic_bonus=2,
        solamnic_enabled=True,
    )
    service = DiplomacyActivationService(gs)

    attempt = service.build_activation_attempt("coastlund")

    assert attempt is not None
    assert attempt.active_side == WS
    assert attempt.ws_rating == 3
    assert attempt.hl_rating == 7
    assert attempt.solamnic_bonus == 2
    assert attempt.target_rating == 5


def test_build_activation_attempt_uses_hl_rating_for_highlord_player():
    gs = _game_state(
        active_player=HL,
        countries={"icewall": _country("icewall", NEUTRAL, (2, 6))},
        solamnic_bonus=9,
        solamnic_enabled=True,
    )
    service = DiplomacyActivationService(gs)

    attempt = service.build_activation_attempt("icewall")

    assert attempt is not None
    assert attempt.active_side == HL
    assert attempt.target_rating == 6
    assert attempt.solamnic_bonus == 0


def test_roll_activation_returns_success_when_roll_is_at_or_below_target():
    gs = _game_state(active_player=WS, countries={})
    service = DiplomacyActivationService(gs)

    with patch("src.game.diplomacy.random.randint", return_value=4):
        result = service.roll_activation(4)

    assert result.roll == 4
    assert result.success is True


def test_roll_activation_returns_failure_when_roll_exceeds_target():
    gs = _game_state(active_player=WS, countries={})
    service = DiplomacyActivationService(gs)

    with patch("src.game.diplomacy.random.randint", return_value=8):
        result = service.roll_activation(7)

    assert result.roll == 8
    assert result.success is False


def test_build_deployment_plan_activates_country_for_alliance_effect():
    gs = _game_state(
        active_player=HL,
        countries={"icewall": _country("icewall", NEUTRAL, (2, 6))},
    )
    service = DiplomacyActivationService(gs)

    plan = service.build_deployment_plan({"alliance": "icewall"}, HL)

    assert plan.country_filter == "icewall"
    assert gs.activated == [("icewall", HL)]
    assert "Deploy forces" in plan.message_text


def test_build_deployment_plan_clears_filter_for_add_units():
    gs = _game_state(active_player=HL, countries={})
    service = DiplomacyActivationService(gs)

    plan = service.build_deployment_plan({"alliance": "icewall", "add_units": True}, HL)

    assert plan.country_filter is None


def test_build_deployment_plan_skips_activation_when_already_activated():
    gs = _game_state(
        active_player=HL,
        countries={"icewall": _country("icewall", NEUTRAL, (2, 6))},
    )
    service = DiplomacyActivationService(gs)

    plan = service.build_deployment_plan(
        {"alliance": "icewall", "alliance_already_activated": True},
        HL,
    )

    assert plan.country_filter == "icewall"
    assert gs.activated == []


def test_resolve_invasion_success_activates_country_and_returns_outcome():
    country = _country("coastlund", NEUTRAL, (5, 3))
    country.strength = 4
    gs = _game_state(active_player=HL, countries={"coastlund": country})
    service = DiplomacyActivationService(gs)

    with patch("src.game.diplomacy.random.randint", return_value=3):
        outcome = service.resolve_invasion("coastlund", {"strength": 6})

    assert outcome.success is True
    assert outcome.winner == WS
    assert gs.activated == [("coastlund", WS)]
    assert "Invader SP" in outcome.message


def test_resolve_invasion_failure_when_no_force():
    country = _country("coastlund", NEUTRAL, (5, 3))
    country.strength = 4
    gs = _game_state(active_player=HL, countries={"coastlund": country})
    service = DiplomacyActivationService(gs)

    outcome = service.resolve_invasion("coastlund", {"strength": 0, "reason": "No force."})

    assert outcome.success is False
    assert outcome.message == "No force."
