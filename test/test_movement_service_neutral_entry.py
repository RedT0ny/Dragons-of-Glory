from types import SimpleNamespace

from src.content.constants import HL, NEUTRAL, WS
from src.game.map import Hex
from src.game.movement import MovementService


def _country(country_id, allegiance):
    return SimpleNamespace(id=country_id, allegiance=allegiance)


def _game_state(active_player, country):
    return SimpleNamespace(
        active_player=active_player,
        get_country_by_hex=lambda col, row: country,
    )


def test_evaluate_neutral_entry_blocks_ws():
    gs = _game_state(WS, _country("icewall", NEUTRAL))
    service = MovementService(gs)

    decision = service.evaluate_neutral_entry(Hex(0, 0))

    assert decision.is_neutral_entry is True
    assert decision.country_id == "icewall"
    assert decision.blocked_message is not None
    assert decision.confirmation_prompt is None


def test_evaluate_neutral_entry_prompts_hl_confirmation():
    gs = _game_state(HL, _country("icewall", NEUTRAL))
    service = MovementService(gs)

    decision = service.evaluate_neutral_entry(Hex(0, 0))

    assert decision.is_neutral_entry is True
    assert decision.country_id == "icewall"
    assert decision.blocked_message is None
    assert decision.confirmation_prompt == "Invade icewall?"


def test_evaluate_neutral_entry_returns_non_neutral_when_country_not_neutral():
    gs = _game_state(HL, _country("solamnia", WS))
    service = MovementService(gs)

    decision = service.evaluate_neutral_entry(Hex(0, 0))

    assert decision.is_neutral_entry is False
