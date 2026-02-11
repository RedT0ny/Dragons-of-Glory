from src.content.constants import HL, WS
from src.content.specs import GamePhase


class PhaseManager:
    def __init__(self, game_state):
        self.game_state = game_state

    def is_automatic_phase(self, phase=None):
        """
        Returns True for phases that always auto-resolve without player input.
        """
        if phase is None:
            phase = self.game_state.phase
        return phase in {
            GamePhase.STRATEGIC_EVENTS,
            GamePhase.ACTIVATION,
            GamePhase.INITIATIVE,
        }

    def should_auto_advance(self):
        """
        Returns True if the current phase should auto-advance based on AI or phase type.
        """
        current_player = self.game_state.current_player
        is_ai = bool(current_player and current_player.is_ai)
        return is_ai or self.is_automatic_phase()

    def advance_phase(self):
        """
        The State Machine: Determines the next phase based on current state.
        This ensures the strict order of the Battle Turn.
        """
        if self.game_state.phase == GamePhase.DEPLOYMENT:
            # If currently the non-initiative player, switch to initiative player
            # If currently the initiative player, deployment is done AND it counts as their Replacements.

            if self.game_state.active_player != self.game_state.initiative_winner:
                self.game_state.active_player = self.game_state.initiative_winner
                # Phase remains DEPLOYMENT for the second player
            else:
                # Initiative winner finished deployment.
                # Proceed directly to movement (Skipping activation, events and initiative phases for this first turn)
                self.game_state.phase = GamePhase.MOVEMENT

        elif self.game_state.phase == GamePhase.REPLACEMENTS:
            # Logic: The player that lost initiative roll goes first in replacements (Handled in nex_turn).
            # First check if active_player is HL, to process draconian production
            if self.game_state.active_player == HL:
                self.game_state.process_draconian_production()
            # Now check if we are in the first or second player replacement round
            if self.game_state.active_player != self.game_state.initiative_winner:
                # That means it's the first player replacing
                self.game_state.active_player = self.game_state.initiative_winner
                # Phase remains REPLACEMENTS for the second player
            else:
                self.game_state.phase = GamePhase.STRATEGIC_EVENTS

        elif self.game_state.phase == GamePhase.STRATEGIC_EVENTS:
            if self.game_state.active_player == self.game_state.initiative_winner:
                # That means it's the event for the first player
                self.game_state.active_player = WS if self.game_state.initiative_winner == HL else HL
                # Phase remains STRATEGIC_EVENTS for the second player
                # Note: since this phase is fully automatic, maybe this is not required
                # and can be handled directly in the controller.
            else:
                self.game_state.phase = GamePhase.ACTIVATION

        elif self.game_state.phase == GamePhase.ACTIVATION:
            if self.game_state.active_player != self.game_state.initiative_winner:
                # That means it's the event for the first player
                self.game_state.active_player = self.game_state.initiative_winner
                # Phase remains ACTIVATION for the second player
            else:
                self.game_state.phase = GamePhase.INITIATIVE

        elif self.game_state.phase == GamePhase.INITIATIVE:
            # Controller must have set_initiative() before calling this
            self.game_state.phase = GamePhase.MOVEMENT
            self.game_state.second_player_has_acted = False

        elif self.game_state.phase == GamePhase.MOVEMENT:
            for unit in self.game_state.units:
                unit.movement_points = getattr(unit, "movement", 0)
                unit.moved_this_turn = False
            self.game_state.phase = GamePhase.COMBAT

        elif self.game_state.phase == GamePhase.COMBAT:
            self.game_state.clear_leader_tactical_overrides()
            for unit in self.game_state.units:
                unit.attacked_this_turn = False
            if not self.game_state.second_player_has_acted:
                # End of First Player's turn (Step 6 done).
                # Start Second Player's turn (Step 7).
                self.game_state.phase = GamePhase.MOVEMENT
                self.game_state.active_player = WS if self.game_state.active_player == HL else HL
                self.game_state.second_player_has_acted = True
            else:
                # End of Second Player's turn. Turn over (Step 8).
                self.next_turn()

    def next_turn(self):
        """Advances the game to the next turn (Step 8)."""
        self.game_state.turn += 1
        self.game_state.phase = GamePhase.REPLACEMENTS
        # Change active_player to the one that lost initiative roll, so they go first in replacements
        self.game_state.active_player = WS if self.game_state.initiative_winner == HL else HL

        # Reset unit flags
        for unit in self.game_state.units:
            unit.movement_points = getattr(unit, 'movement', 0)  # Reset MPs
            unit.attacked_this_turn = False
            unit.moved_this_turn = False
            # Handle status recovery/exhaustion here if needed

        # Check events
        self.game_state.check_events()
