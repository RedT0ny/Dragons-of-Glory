from types import SimpleNamespace

from src.content.constants import HL, WS
from src.content.specs import GamePhase
from src.game.game_state import GameState


def test_combat_bonus_event_is_applied_to_drawing_player():
    gs = GameState()
    gs.active_player = WS
    gs.players = {
        WS: SimpleNamespace(allegiance=WS, grant_asset=lambda asset_id, game_state: None),
        HL: SimpleNamespace(allegiance=HL, grant_asset=lambda asset_id, game_state: None),
    }

    gs.apply_event_effect(SimpleNamespace(effects={"combat_bonus": 1}))
    assert gs.get_combat_bonus(WS) == 1
    assert gs.get_combat_bonus(HL) == 0


def test_combat_bonus_clears_at_end_of_each_players_combat_phase():
    gs = GameState()
    gs.phase = GamePhase.COMBAT
    gs.initiative_winner = WS
    gs.second_player_has_acted = False
    gs.active_player = WS
    gs.players = {
        WS: SimpleNamespace(allegiance=WS, grant_asset=lambda asset_id, game_state: None),
        HL: SimpleNamespace(allegiance=HL, grant_asset=lambda asset_id, game_state: None),
    }
    gs.units = []
    gs.map = SimpleNamespace()
    gs.resolve_end_of_combat_conquest = lambda: None
    gs.clear_leader_tactical_overrides = lambda: None
    gs.combat_bonuses = {HL: 3, WS: 2}

    # First player's combat ends: clear only that player's combat bonus.
    gs.phase_manager.advance_phase()
    assert gs.phase == GamePhase.MOVEMENT
    assert gs.active_player == HL
    assert gs.combat_bonuses == {HL: 3, WS: 0}

    # Second player's combat ends: clear second player's bonus too.
    gs.phase = GamePhase.COMBAT
    gs.phase_manager.advance_phase()
    assert gs.combat_bonuses == {HL: 0, WS: 0}
