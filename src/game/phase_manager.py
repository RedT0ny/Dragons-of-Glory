import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from src.content import loader
from src.content.config import CALENDAR_DATA
from src.content.constants import HL, WS
from src.content.specs import GamePhase


class CalendarService:
    """
    Lazy-loading calendar data service.
    Calendar is global (same mapping for all scenarios).
    Scenarios may start at different turns but mapping is constant.
    """
    _instance = None
    _calendar_data = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_calendar(self):
        """Lazy load calendar CSV once and cache it."""
        if self._calendar_data is None:
            try:
                self._calendar_data = loader.load_calendar_csv(CALENDAR_DATA)
            except Exception as exc:
                print(f"Failed to load calendar data: {exc}")
                self._calendar_data = {}
        return self._calendar_data

    def get_spec(self, turn: int):
        """Returns calendar spec for turn or None if missing."""
        return self._load_calendar().get(turn)

    def upper_label(self, turn: int) -> str:
        """Returns upper_label for turn or empty string if missing."""
        spec = self.get_spec(turn)
        return spec.upper_label if spec else ""


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
            GamePhase.INITIATIVE,
            GamePhase.SUPPLY,
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
        if getattr(self.game_state, "game_over", False):
            return

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
            self.game_state.on_finish_replacements_round_for_player(self.game_state.active_player)
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
                # Activation bonuses are only valid during Step 3 of the current battle turn.
                self.game_state.finalize_activation_phase()
                self.game_state.phase = GamePhase.INITIATIVE

        elif self.game_state.phase == GamePhase.INITIATIVE:
            # Controller must have set_initiative() before calling this
            self.game_state.phase = GamePhase.MOVEMENT
            self.game_state.second_player_has_acted = False
            self.game_state.prepare_for_movement_phase()

        elif self.game_state.phase == GamePhase.MOVEMENT:
            self.game_state.phase = GamePhase.COMBAT

        elif self.game_state.phase == GamePhase.COMBAT:
            self.game_state.finalize_combat_phase()
            if not self.game_state.second_player_has_acted:
                # End of First Player's turn.
                # Start Second Player's turn (Steps 5 & 6).
                self.game_state.phase = GamePhase.MOVEMENT
                self.game_state.active_player = WS if self.game_state.active_player == HL else HL
                self.game_state.second_player_has_acted = True
                self.game_state.prepare_for_movement_phase()
            else:
                # End of Second Player's turn. Supply phase (Step 7).
                supply_mode = str(getattr(self.game_state, "supply", "standard")).strip().lower()
                if supply_mode == "advanced":
                    self.game_state.phase = GamePhase.SUPPLY
                else:
                    self.next_turn()

        elif self.game_state.phase == GamePhase.SUPPLY:
            self.game_state.resolve_supply_phase()
            self.next_turn()

        try:
            self.game_state.invalidate_overlays({"threat"})
        except Exception:
            pass
        #self.game_state.evaluate_victory_conditions()

    def next_turn(self):
        """Advances the game to the next turn (Step 8)."""
        if getattr(self.game_state, "game_over", False):
            return
        self.game_state.begin_next_turn()


class TurnAction(Enum):
    NONE = "none"
    REQUEST_HUMAN_DEPLOYMENT = "request_human_deployment"
    REQUEST_HUMAN_REPLACEMENTS = "request_human_replacements"
    REQUEST_HUMAN_EVENT_DIALOG = "request_human_event_dialog"
    REQUEST_HUMAN_ACTIVATION = "request_human_activation"


@dataclass(frozen=True)
class TurnOutcome:
    action: TurnAction = TurnAction.NONE
    payload: Optional[dict] = None
    advanced: bool = False


class TurnEngine:
    """
    Pure turn/phase orchestration.
    - Executes non-UI phase logic.
    - Emits action requests when user interaction is required.
    """

    def __init__(self, game_state, ai_baseline, attempt_invasion: Optional[Callable[..., Any]] = None):
        self.game_state = game_state
        self.ai_baseline = ai_baseline
        self.attempt_invasion = attempt_invasion
        self._last_phase_header_key = None

    def _log_phase_header_once(self, message: str):
        key = (
            int(getattr(self.game_state, "turn", 0) or 0),
            getattr(self.game_state, "active_player", None),
            getattr(self.game_state, "phase", None),
        )
        if self._last_phase_header_key == key:
            return
        self._last_phase_header_key = key
        print(message)

    def step(self) -> TurnOutcome:
        current_phase = self.game_state.phase
        active_player = self.game_state.active_player
        current_player = self.game_state.current_player
        is_ai = bool(current_player and current_player.is_ai)

        if current_phase == GamePhase.DEPLOYMENT:
            self._log_phase_header_once(f"Step 0: Deployment Phase - {active_player}")
            if is_ai:
                deployed = self.ai_baseline.deploy_all_ready_units(active_player)
                print(f"AI deployment complete. Deployed: {deployed}")
                self.game_state.advance_phase()
                return TurnOutcome(advanced=True)
            return TurnOutcome(
                action=TurnAction.REQUEST_HUMAN_DEPLOYMENT,
                payload={"active_player": active_player},
            )

        if current_phase == GamePhase.REPLACEMENTS:
            self._log_phase_header_once(f"Step 1: Replacements Phase - {active_player}")
            if is_ai:
                conscriptions, deployed = self.ai_baseline.process_replacements(active_player)
                print(f"AI replacements complete. Conscriptions: {conscriptions}, deployed: {deployed}")
                self.game_state.advance_phase()
                return TurnOutcome(advanced=True)
            return TurnOutcome(
                action=TurnAction.REQUEST_HUMAN_REPLACEMENTS,
                payload={"active_player": active_player},
            )

        if current_phase == GamePhase.STRATEGIC_EVENTS:
            self._log_phase_header_once(f"Step 2: Strategic Events - {active_player}")
            event = self.game_state.event_system.draw_strategic_event(active_player)
            if event:
                event.force_activate(self.game_state)
                if is_ai:
                    assigned = self.ai_baseline.assign_assets(active_player)
                    if assigned:
                        print(f"AI asset assignment complete. Assigned: {assigned}")
                    self.game_state.advance_phase()
                    return TurnOutcome(advanced=True)
                return TurnOutcome(
                    action=TurnAction.REQUEST_HUMAN_EVENT_DIALOG,
                    payload={"event": event, "active_player": active_player},
                )
            self.game_state.advance_phase()
            return TurnOutcome(advanced=True)

        if current_phase == GamePhase.ACTIVATION:
            self._log_phase_header_once(f"Step 3: Activation - {active_player}")
            if not self.game_state.has_neutral_countries():
                print("No neutral countries remain. Skipping Activation phase.")
                self.game_state.advance_phase()
                return TurnOutcome(advanced=True)

            if is_ai:
                success, country_id = self.ai_baseline.perform_activation(active_player)
                if success:
                    print(f"AI activated country {country_id}.")
                else:
                    print("AI activation failed or skipped.")
                self.game_state.advance_phase()
                return TurnOutcome(advanced=True)

            return TurnOutcome(
                action=TurnAction.REQUEST_HUMAN_ACTIVATION,
                payload={"active_player": active_player},
            )

        if current_phase == GamePhase.INITIATIVE:
            hl_roll = random.randint(1, 4)
            ws_roll = random.randint(1, 4)
            if hl_roll == ws_roll:
                winner = self.game_state.initiative_winner
            elif hl_roll > ws_roll:
                winner = HL
            else:
                winner = WS
            self._log_phase_header_once(f"Step 4: Initiative. Winner: {winner}")
            self.game_state.set_initiative(winner)
            self.game_state.advance_phase()
            return TurnOutcome(advanced=True)

        if current_phase == GamePhase.MOVEMENT:
            self._log_phase_header_once(f"Step 5: Movement phase - {active_player}")
            if is_ai:
                assigned = self.ai_baseline.assign_assets(active_player)
                if assigned:
                    print(f"AI asset assignment complete. Assigned: {assigned}")
            if is_ai:
                moved = self.ai_baseline.execute_best_movement(
                    active_player,
                    attempt_invasion=self.attempt_invasion,
                )
                if not moved:
                    self.game_state.advance_phase()
                    return TurnOutcome(advanced=True)
            return TurnOutcome()

        if current_phase == GamePhase.COMBAT:
            self._log_phase_header_once(f"Step 6: Combat phase - {active_player}")
            if is_ai:
                fought = self.ai_baseline.execute_best_combat(active_player)
                if not fought:
                    self.game_state.advance_phase()
                    return TurnOutcome(advanced=True)
            return TurnOutcome()

        if current_phase == GamePhase.SUPPLY:
            self._log_phase_header_once("Step 7: Supply phase")
            self.game_state.advance_phase()
            return TurnOutcome(advanced=True)

        return TurnOutcome()
