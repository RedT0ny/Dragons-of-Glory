from types import SimpleNamespace
from unittest.mock import patch

from src.content.constants import HL, WS
from src.content.specs import CountrySpec, GamePhase, LocationSpec
from src.game.country import Country
from src.game.diplomacy import DiplomacyActivationService
from src.game.game_state import GameState


def _country(country_id: str, alignment=(5, -1), allegiance="neutral"):
    spec = CountrySpec(
        id=country_id,
        capital_id=f"{country_id}_cap",
        strength=10,
        allegiance=allegiance,
        alignment=alignment,
        color="#000000",
        locations=[LocationSpec(id=f"{country_id}_cap", loc_type="city", coords=(1, 1), is_capital=True)],
        territories=[(1, 1)],
    )
    return Country(spec)


def test_activation_bonus_event_subtracts_from_roll_for_current_turn():
    gs = GameState()
    gs.active_player = WS
    gs.players = {
        WS: SimpleNamespace(allegiance=WS, grant_asset=lambda asset_id, game_state: None),
        HL: SimpleNamespace(allegiance=HL, grant_asset=lambda asset_id, game_state: None),
    }
    gs.countries = {"palanthas": _country("palanthas", alignment=(5, -1))}

    gs.apply_event_effect(SimpleNamespace(effects={"activation_bonus": 2}))
    svc = DiplomacyActivationService(gs)
    attempt = svc.build_activation_attempt("palanthas")

    assert attempt is not None
    assert attempt.target_rating == 5
    assert attempt.event_activation_bonus == 2

    with patch("random.randint", return_value=7):
        result = svc.roll_activation(attempt.target_rating, roll_bonus=attempt.event_activation_bonus)

    assert result.roll == 7
    assert result.effective_roll == 5
    assert result.success is True


def test_activation_bonus_clears_when_leaving_activation_phase():
    gs = GameState()
    gs.activation_bonuses = {HL: 1, WS: 2}
    gs.phase = GamePhase.ACTIVATION
    gs.initiative_winner = WS
    gs.active_player = HL

    # First player activation ends; phase remains ACTIVATION and bonus persists.
    gs.phase_manager.advance_phase()
    assert gs.phase == GamePhase.ACTIVATION
    assert gs.active_player == WS
    assert gs.activation_bonuses == {HL: 1, WS: 2}

    # Initiative winner activation ends; now activation phase closes and bonuses are cleared.
    gs.phase_manager.advance_phase()
    assert gs.phase == GamePhase.INITIATIVE
    assert gs.activation_bonuses == {HL: 0, WS: 0}
