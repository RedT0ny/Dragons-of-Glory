# Conceptual example for game flow
from PySide6.QtCore import QObject, QTimer, Qt
from time import monotonic
import shiboken6

from src.content.tools import TextFormatter
from src.content.translator import Translator
from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitState
from src.game.diplomacy import DiplomacyService
from src.game.ai_baseline import BaselineAIPlayer
from src.game.phase_manager import TurnAction, TurnEngine
from src.content.runtime_diagnostics import RuntimeDiagnostics
from src.game.map import Hex


class GameController(QObject):
    def __init__(
        self,
        game_state,
        view,
        highlord_ai=False,
        whitestone_ai=False,
        difficulty="normal",
        combat_details="brief",
        supply="standard",
        deployment="canonical",
    ):
        """Initialize the game controller with state, view, and configuration.
        
        Args:
            game_state: Core game state object managing all game data.
            view: Game view/UI instance for rendering and user interaction.
            highlord_ai: Whether the Highlord faction is AI-controlled (default False).
            whitestone_ai: Whether the Whitestone faction is AI-controlled (default False).
            difficulty: Game difficulty level (default "normal").
            combat_details: Level of combat detail to display (default "brief").
            supply: Supply ruleset variant (default "standard").
        """
        super().__init__()
        self.game_state = game_state
        self.view = view
        self.replacements_dialog = None
        self.difficulty = str(difficulty).strip().lower()
        self.combat_details = str(combat_details).strip().lower()
        self.supply = str(supply).strip().lower()
        self.deployment = str(deployment).strip().lower()
        self.game_state.difficulty = self.difficulty
        self.game_state.combat_details = self.combat_details
        self.game_state.supply = self.supply
        self.game_state.deployment_mode = self.deployment

        # Apply AI configuration to Players directly
        if HL in self.game_state.players:
            self.game_state.players[HL].set_ai(highlord_ai)
        if WS in self.game_state.players:
            self.game_state.players[WS].set_ai(whitestone_ai)

        # Timer to drive AI actions periodically
        self.ai_timer = QTimer()
        self.ai_timer.timeout.connect(self.process_game_turn)
        self.ai_timer.setInterval(1000) # 1 second between AI moves

        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self._invasion_deployment_active = False
        self._invasion_deployment_country_id = None
        self._invasion_deployment_allegiance = None
        from src.game.combat import CombatClickHandler
        self.combat_click_handler = CombatClickHandler(self.game_state, self.view)
        self.movement_service = self.game_state.movement_service
        self.deployment_service = self.game_state.deployment_service
        self._processing_automatic_phases = False  # Flag to prevent reentry
        self._map_view_signals_connected = False  # Track if map view signals are connected
        self.diplomacy_service = DiplomacyService(self.game_state)
        self.ai_baseline = BaselineAIPlayer(self.game_state, self.movement_service, self.diplomacy_service)
        self.translator = Translator()
        self.turn_engine = TurnEngine(
            self.game_state,
            self.ai_baseline,
            attempt_invasion=self._attempt_invasion,
        )
        self._movement_undo_context = None
        self._deferred_epoch = 0
        self._end_phase_transition_pending = False
        self._last_end_phase_request_at = 0.0
        self._deployment_session_unit_ids = set()
        self._victory_announced = False
        self._processing_turn_tick = False
        self._replacements_refresh_queued = False
        self._pending_phase_advance_after_deployment = False

    def get_runtime_config(self):
        """Return current runtime configuration for saving/restoring.
        
        Returns:
            dict: Configuration with keys highlord_ai, whitestone_ai, difficulty,
                combat_details, supply.
        """
        return {
            "highlord_ai": bool(self.game_state.players.get(HL).is_ai) if HL in self.game_state.players else False,
            "whitestone_ai": bool(self.game_state.players.get(WS).is_ai) if WS in self.game_state.players else False,
            "difficulty": self.difficulty,
            "combat_details": self.combat_details,
            "supply": self.supply,
            "deployment": self.deployment,
        }

    def apply_runtime_config(self, config: dict):
        """Apply runtime configuration to controller and game state.
        
        Args:
            config: Dictionary containing runtime settings to apply, namely:
                - highlord_ai: Whether the Highlord faction is AI-controlled (default False).
                - whitestone_ai: Whether the Whitestone faction is AI-controlled (default False).
                - difficulty: Game difficulty level (default "normal").
                - combat_details: Level of combat detail to display (default "brief").
                - supply: Supply ruleset variant (default "standard").
        """
        hl_ai = bool(config.get("highlord_ai", False))
        ws_ai = bool(config.get("whitestone_ai", False))
        self.difficulty = str(config.get("difficulty", self.difficulty)).strip().lower()
        self.combat_details = str(config.get("combat_details", self.combat_details)).strip().lower()
        self.supply = str(config.get("supply", self.supply)).strip().lower()
        self.deployment = str(config.get("deployment", self.deployment)).strip().lower()
        self.game_state.difficulty = self.difficulty
        self.game_state.combat_details = self.combat_details
        self.game_state.supply = self.supply
        self.game_state.deployment_mode = self.deployment

        if HL in self.game_state.players:
            self.game_state.players[HL].set_ai(hl_ai)
        if WS in self.game_state.players:
            self.game_state.players[WS].set_ai(ws_ai)
        if hasattr(self.game_state, "invalidate_overlays"):
            self.game_state.invalidate_overlays({"control", "territory", "supply", "ws_power", "hl_power", "threat"})

    def _schedule_deferred(self, callback):
        """Schedule a callback to run on the next Qt event loop iteration.
        
        Uses epoch tracking to discard stale callbacks from previous states.
        
        Args:
            callback: Callable to execute deferred.
        """
        epoch = self._deferred_epoch
        callback_name = getattr(callback, "__name__", callback.__class__.__name__)
        QTimer.singleShot(1, lambda: self._run_deferred_if_current(epoch, callback, callback_name))

    def _is_human_interactive_turn(self) -> bool:
        """
        True only when the active side is human and the phase expects direct input.
        """
        current_player = self.game_state.current_player
        if not current_player or current_player.is_ai:
            return False
        return self.game_state.phase in {GamePhase.DEPLOYMENT, GamePhase.REPLACEMENTS, GamePhase.MOVEMENT, GamePhase.COMBAT}

    def _run_deferred_if_current(self, epoch, callback, callback_name="callback"):
        """Execute a deferred callback only if the epoch matches current state.
        
        Prevents stale callbacks from previous game states from running.
        
        Args:
            epoch: Epoch value when the callback was scheduled.
            callback: Callable to execute if epoch matches.
            callback_name: Name for diagnostics logging (default "callback").
        """
        if epoch != self._deferred_epoch:
            RuntimeDiagnostics.record_event(
                f"Deferred skipped (epoch mismatch): {callback_name}"
            )
            return
        RuntimeDiagnostics.record_event(f"Deferred start: {callback_name}")
        try:
            callback()
        finally:
            RuntimeDiagnostics.record_event(f"Deferred end: {callback_name}")

    def prepare_for_state_load(self):
        """
        Quiesce controller/UI state before loading a new save into the same runtime objects.
        This invalidates pending deferred callbacks tied to previous state.
        """
        self.ai_timer.stop()
        self._deferred_epoch += 1
        self._processing_automatic_phases = False
        self._end_phase_transition_pending = False
        self._last_end_phase_request_at = 0.0
        self._pending_phase_advance_after_deployment = False
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.movement_service.clear_movement_undo()
        if self.replacements_dialog and shiboken6.isValid(self.replacements_dialog):
            self.replacements_dialog.close()
            self.replacements_dialog = None
        if self.combat_click_handler:
            self.combat_click_handler.reset_selection()
        self.view.highlight_movement_range([])
        self._end_deployment_session()

    def _begin_deployment_session(self):
        """Initialize a new deployment session to track deployed unit IDs."""
        self._deployment_session_unit_ids = set()

    def _end_deployment_session(self):
        """Clear the current deployment session and reset tracked unit IDs."""
        self._deployment_session_unit_ids.clear()

    def _is_deployment_session_active(self):
        """Check if a deployment session is currently active.
        
        Returns:
            bool: True if the replacements dialog is visible (deployment in progress).
        """
        return self._is_replacements_dialog_visible()

    def _is_replacements_dialog_visible(self):
        """Check if the replacements/deployment dialog is open and visible.
        
        Returns:
            bool: True if dialog exists, is valid, and currently visible.
        """
        dlg = self.replacements_dialog
        return bool(dlg and shiboken6.isValid(dlg) and dlg.isVisible())

    def _can_redeploy_unit_now(self, unit):
        """Check if a unit is eligible for redeployment in the current session.
        
        Args:
            unit: Unit object to check eligibility for.
            
        Returns:
            bool: True if unit can be redeployed.
        """
        if not self._is_deployment_session_active():
            return False
        if getattr(self.view, "deploying_unit", None) is not None:
            return False
        if unit.id not in self._deployment_session_unit_ids:
            return False
        expected_allegiance = self.game_state.active_player
        if self._invasion_deployment_active and self._invasion_deployment_allegiance:
            expected_allegiance = self._invasion_deployment_allegiance
        if unit.allegiance != expected_allegiance:
            return False
        if unit.status != UnitState.ACTIVE or not unit.is_on_map:
            return False
        return True

    def on_map_units_clicked(self, clicked_units):
        """Allow redeploying units placed during the current deployment session."""
        if not self._is_human_interactive_turn() and not self._is_deployment_session_active():
            return
        # Ignore stack-click redeploy logic while the user is actively placing a unit.
        # Deployment clicks on occupied hexes emit units_clicked before placement handling.
        if getattr(self.view, "deploying_unit", None) is not None:
            return
        if not clicked_units:
            return
        candidate = next((u for u in clicked_units if self._can_redeploy_unit_now(u)), None)
        if not candidate:
            return
        self._return_unit_to_ready_for_redeployment(candidate)

    def on_map_depleted_stack_clicked(self, clicked_units):
        """Controller-owned depleted merge eligibility/rule handling."""
        if self.game_state.phase != GamePhase.REPLACEMENTS:
            return
        if not self._is_human_interactive_turn():
            return
        if not clicked_units:
            return

        candidates = [
            u for u in clicked_units
            if u.status == UnitState.DEPLETED
            and u.allegiance == self.game_state.active_player
            and (u.is_fleet() or u.is_army())
        ]
        if len(candidates) < 2:
            return

        from collections import defaultdict
        by_group = defaultdict(list)
        for unit in candidates:
            by_group[self.game_state.get_replacement_group_key(unit)].append(unit)

        for _, units in by_group.items():
            if len(units) >= 2:
                self.on_depleted_merge_requested(units[0], units[1])
                break

    def _return_unit_to_ready_for_redeployment(self, unit):
        """Return a unit to READY state for redeployment, removing it from the board.
        
        Resets unit movement/attack flags and schedules UI sync.
        
        Args:
            unit: Unit object to return to ready state.
        """
        self.game_state.movement_service.remove_unit_from_board(
            unit,
            escaped=False,
            clear_transport=True,
            clear_river_hexside=True,
            remove_passengers=True,
        )
        unit.status = UnitState.READY
        if unit.movement_points:
            unit.movement_points = unit.movement
        if unit.moved_this_turn:
            unit.moved_this_turn = False
        if unit.attacked_this_turn:
            unit.attacked_this_turn = False

        def _deferred_redeploy_sync():
            if self._is_replacements_dialog_visible():
                self.replacements_dialog.refresh()
            self.view.sync_with_model()
            self._refresh_info_panel()
            if self._is_replacements_dialog_visible():
                self.on_ready_unit_clicked(unit, self.replacements_dialog.allow_territory_deploy)

        self._schedule_deferred(_deferred_redeploy_sync)
        print(f"Unit {TextFormatter.format_unit_log_string(unit)} returned to READY for redeployment.")

    def start_game(self):
        """Initializes the loop and immediately processes the first phase."""
        self.process_game_turn()

    def start_new_game(self, scenario_spec):
        """
        Start a new scenario using the existing runtime objects.
        Preserves runtime configuration (AI flags and ruleset options).
        """
        runtime_config = self.get_runtime_config()
        self.prepare_for_state_load()
        self.game_state.load_scenario(scenario_spec)
        self.apply_runtime_config(runtime_config)
        self._after_state_reload()

    def save_game(self, path: str):
        """Persist current game state to disk."""
        self.game_state.save_state(path)

    def load_game(self, path: str):
        """Load a saved game into the existing runtime objects."""
        self.prepare_for_state_load()
        self.game_state.load_state(path)
        self._after_state_reload()

    def _after_state_reload(self):
        """Refresh view widgets after scenario/save load and resume turn processing."""
        self._victory_announced = False
        self.view.reset_view_for_new_map()
        self.view.sync_with_model()

        main_window = self.view.window()
        if hasattr(main_window, "info_panel"):
            main_window.info_panel.set_game_state(self.game_state)
            main_window.info_panel.refresh()
        if hasattr(main_window, "status_tab"):
            main_window.status_tab.refresh()
        if hasattr(main_window, "assets_tab"):
            main_window.assets_tab.refresh()

        self._schedule_deferred(self.process_game_turn)

    def check_active_player(self):
        """Checks if the loop should continue running automatically."""
        # Start timer if it's an AI turn OR if the phase is automatic
        if self.game_state.phase_manager.should_auto_advance():
            if not self.ai_timer.isActive():
                self.ai_timer.start()
        else:
            # Human turn in an interactive phase (Replacements, Movement, Combat)
            # We stop the timer and wait for the user to click "End Phase"
            self.ai_timer.stop()

    def process_game_turn(self):
        """
        Central loop for processing the game flow.
        Handles all GamePhases
        """
        if self._processing_turn_tick:
            return
        self._processing_turn_tick = True
        try:
            if self._invasion_deployment_active and self._invasion_deployment_allegiance:
                invasion_player = self.game_state.players.get(self._invasion_deployment_allegiance)
                if invasion_player and not invasion_player.is_ai:
                    print("AI paused for invasion deployment")
                    self.ai_timer.stop()
                    return
            if self.game_state.game_over:
                self._announce_victory_if_needed()
                self.ai_timer.stop()
                return

            self._end_phase_transition_pending = False

            if self._processing_automatic_phases:
                return

            current_phase = self.game_state.phase
            active_player = self.game_state.active_player
            state_before = (current_phase, active_player)

            if current_phase == GamePhase.MOVEMENT:
                context = (self.game_state.turn, active_player, current_phase)
                if self._movement_undo_context != context:
                    self.movement_service.clear_movement_undo()
                    self._movement_undo_context = context

            outcome = self.turn_engine.step()
            if self._handle_turn_action(outcome.action, outcome.payload):
                # Keep turn header in sync even when step() requests human interaction
                # and returns early (e.g. Replacements/Event/Activation dialogs).
                self._refresh_turn_panel()
                self.connect_map_view_signals()
                self.check_active_player()
                return

            self.view.sync_with_model()
            self._refresh_info_panel()
            self._refresh_turn_panel()
            self._announce_victory_if_needed()
            self.connect_map_view_signals()
            self.check_active_player()

            state_after = (self.game_state.phase, self.game_state.active_player)
            if state_before[0] in {GamePhase.ACTIVATION, GamePhase.COMBAT} and self.game_state.phase != state_before[0]:
                self._refresh_minimap_allegiance()
            if state_after != state_before and not self.game_state.phase_manager.should_auto_advance():
                self._schedule_deferred(self.process_game_turn)
        finally:
            self._processing_turn_tick = False

    def _handle_turn_action(self, action: TurnAction, payload: dict | None) -> bool:
        """Process turn actions returned by the turn engine.
        
        Handles human interaction requests (deployment, events, activation) and
        pauses the turn loop when waiting for user input.
        
        Args:
            action: TurnAction enum value indicating the action to handle.
            payload: Additional data for the action, or None.
            
        Returns:
            bool: True if the action requires pausing for human input, False otherwise.
        """
        payload = payload or {}

        if action == TurnAction.NONE:
            return False

        if action in {TurnAction.REQUEST_HUMAN_DEPLOYMENT, TurnAction.REQUEST_HUMAN_REPLACEMENTS}:
            if (
                action == TurnAction.REQUEST_HUMAN_DEPLOYMENT
                and str(getattr(self.game_state, "deployment_mode", self.deployment)).strip().lower() == "canonical"
            ):
                deployed = self.game_state.apply_canonical_deployment(
                    payload.get("active_player", self.game_state.active_player)
                )
                if deployed is not None:
                    print(f"Canonical deployment complete. Deployed: {deployed}")
                    self.game_state.advance_phase()
                    return False
            if not self._is_replacements_dialog_visible():
                from src.gui.replacements_dialog import ReplacementsDialog
                self.replacements_dialog = ReplacementsDialog(
                    self.game_state,
                    self.view,
                    parent=self.view.window(),
                )
                self._connect_replacements_dialog_signals()
                if action == TurnAction.REQUEST_HUMAN_DEPLOYMENT:
                    self.replacements_dialog.setWindowTitle(
                        f"Deployment Phase - {payload.get('active_player', self.game_state.active_player)}"
                    )
                self.replacements_dialog.show()
                self._begin_deployment_session()
            return True

        if action == TurnAction.REQUEST_HUMAN_EVENT_DIALOG:
            event = payload.get("event")
            active_player = payload.get("active_player", self.game_state.active_player)
            if event is None:
                self.game_state.advance_phase()
                return False
            from src.gui.event_dialog import EventDialog
            dlg = EventDialog(event)
            dlg.exec()
            effects = dict(getattr(event.spec, "effects", {}) or {})
            if "alliance" in effects or "add_units" in effects:
                self._handle_deployment_from_event(effects, active_player)
                self._refresh_turn_panel()
                return True
            if getattr(event.spec, "event_type", None) == "artifact":
                asset_id = effects.get("grant_asset")
                self.open_assets_tab_for_assignment(asset_id)
                self._refresh_turn_panel()
                return True
            self.game_state.advance_phase()
            return False

        if action == TurnAction.REQUEST_HUMAN_ACTIVATION:
            from src.gui.diplomacy_dialog import DiplomacyDialog
            from PySide6.QtWidgets import QDialog

            self.ai_timer.stop()
            active_player = payload.get("active_player", self.game_state.active_player)
            dlg = DiplomacyDialog(self.game_state, self.view.window())
            dlg.country_activated.connect(self.handle_country_activation)
            dlg_result = dlg.exec()

            if dlg.activated_country_id:
                country_id = dlg.activated_country_id
                self._handle_deployment_from_event(
                    {"alliance": country_id, "alliance_already_activated": True},
                    active_player,
                )
                self._refresh_turn_panel()
                return True

            if dlg_result != QDialog.Accepted:
                print("Activation attempt finished or skipped.")
            else:
                print("Activation attempt finished or skipped.")
            self.game_state.advance_phase()
            return False

        return False

    def _announce_victory_if_needed(self):
        """Display victory message if the game is over and not yet announced."""
        if not self.game_state.game_over or self._victory_announced:
            return
        self._victory_announced = True
        winner = (self.game_state.winner or "draw").title()
        reason = self.game_state.victory_reason or "victory_conditions"
        points = getattr(self.game_state, "victory_points", {})
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self.view.window(),
            "Game Over",
            f"Winner: {winner}\nReason: {reason}\n"
            f"Highlord points: {points.get(HL, 0)}\nWhitestone points: {points.get(WS, 0)}",
        )

    def connect_map_view_signals(self):
        """Connect signals from map view to controller."""
        if not hasattr(self.view, 'unit_deployment_requested'):
            return
            
        if not self._map_view_signals_connected:
            self.view.unit_deployment_requested.connect(self.handle_unit_deployment)
            if hasattr(self.view, "depleted_merge_requested"):
                self.view.depleted_merge_requested.connect(self.on_depleted_merge_requested)
            self._map_view_signals_connected = True
            print("Map view signals connected to controller")

    def _refresh_info_panel(self):
        """Helper to refresh side panel if accessible."""
        main_window = self.view.window()
        if hasattr(main_window, 'info_panel'):
            # Stability guard: avoid frequent mini-map scene churn during high-frequency
            # movement/combat updates.
            if self.game_state.phase not in {GamePhase.MOVEMENT, GamePhase.COMBAT}:
                main_window.info_panel.refresh()
            main_window.info_panel.set_undo_enabled(
                self.game_state.phase == GamePhase.MOVEMENT and self.movement_service.can_undo_movement()
            )

    def _refresh_minimap_allegiance(self):
        """Refresh the minimap's allegiance colors if available."""
        main_window = self.view.window()
        info_panel = getattr(main_window, "info_panel", None)
        mini_map = getattr(info_panel, "mini_map", None) if info_panel else None
        if not mini_map:
            return
        if not getattr(mini_map, "map_rendered", False):
            mini_map.sync_with_model()
        else:
            mini_map.update_allegiance_colors()

    def _refresh_turn_panel(self):
        """Update the main window's turn panel with current game state info.
        
        Also toggles the End Phase button based on whether it's a human interactive turn.
        """
        main_window = self.view.window()
        if not hasattr(main_window, "update_turn_panel"):
            return

        turn = self.game_state.turn
        calendar_upper = self.game_state.calendar.upper_label(turn)

        main_window.update_turn_panel(
            active_player=self.game_state.active_player,
            turn=turn,
            calendar_upper_label=calendar_upper,
            phase_label=self._format_phase_label(self.game_state.phase),
        )

        # Enable/disable End Phase button based on whether it's a human interactive turn
        if hasattr(main_window, "info_panel"):
            is_human_turn = self._is_human_interactive_turn()
            main_window.info_panel.set_end_phase_enabled(is_human_turn)

    @staticmethod
    def _format_phase_label(phase):
        """Format a GamePhase enum into a human-readable label.
        
        Args:
            phase: GamePhase enum value to format.
            
        Returns:
            str: Formatted phase label (e.g., "Deployment Phase").
        """
        if hasattr(phase, "name"):
            return phase.name.replace("_", " ").title()
        return str(phase)

    def open_assets_tab_for_assignment(self, asset_id=None):
        """
        Switches to Assets tab and prompts user.
        """
        main_window = self.view.window()

        # 1. Switch Tab
        if hasattr(main_window, 'tabs') and hasattr(main_window, 'assets_tab'):
            # Refresh assets tab to show new item BEFORE switching view
            main_window.assets_tab.refresh()

            # Switch the view
            main_window.tabs.setCurrentWidget(main_window.assets_tab)

            # Pre-select the new asset if ID provided
            if asset_id:
                main_window.assets_tab.select_asset_by_id(asset_id)

        # 2. Show Popup
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(main_window, "New Artifact",
                                "You have received an artifact!\n\n"
                                "Assign it to an unequipped unit using the panel.\n"
                                "Click 'End Turn' (End Phase) when ready.")

        # 3. Stop Timer (if it was running)
        self.ai_timer.stop()
        # The game flow is now paused until on_end_phase_clicked is called.

    def on_end_phase_clicked(self):
        """Call this when Human clicks 'End Phase' button."""
        now = monotonic()
        # Ignore key/button repeats that arrive within the same interaction burst.
        if now - self._last_end_phase_request_at < 0.2:
            return
        self._last_end_phase_request_at = now

        if self._invasion_deployment_active:
            if self.replacements_dialog and shiboken6.isValid(self.replacements_dialog):
                self.replacements_dialog.close()
                self.replacements_dialog = None
            self._end_deployment_session()
            self._invasion_deployment_active = False
            self._invasion_deployment_country_id = None
            self._invasion_deployment_allegiance = None
            self.selected_units_for_movement = []
            self.neutral_warning_hexes = set()
            self.view.highlight_movement_range([])
            self.view.sync_with_model()
            self._refresh_info_panel()
            self.movement_service.clear_movement_undo()
            return

        # Drop repeated "End Phase" triggers until the queued phase transition is processed.
        if self._end_phase_transition_pending:
            return
        self._end_phase_transition_pending = True
        self._pending_phase_advance_after_deployment = False

        # Close replacement dialog if open
        if self.replacements_dialog and shiboken6.isValid(self.replacements_dialog):
            self.replacements_dialog.close()
            self.replacements_dialog = None
        self._end_deployment_session()
        self.view.clear_highlights()
        self.view.deploying_unit = None

        # Clear movement highlights/selection
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.movement_service.clear_movement_undo()
        def _deferred_end_phase_view_update():
            self.view.highlight_movement_range([])
            self.view.sync_with_model()
            self._refresh_info_panel()
        self._schedule_deferred(_deferred_end_phase_view_update)

        self.game_state.advance_phase()

        # Trigger the loop again to handle the next state immediately.
        # This ensures that if the next state is also Human-controlled (e.g., P2 Replacements),
        # the UI (Dialogs) for that player will be initialized.
        # Use QTimer.singleShot to avoid potential recursion issues
        self._schedule_deferred(self.process_game_turn)

    def execute_simple_ai_logic(self, side):
        """Execute basic AI movement logic for the given side.
        
        Args:
            side: Allegiance side (e.g., HL, WS) to run AI logic for.
            
        Returns:
            Result of the AI movement execution.
        """
        return self.ai_baseline.execute_best_movement(side, attempt_invasion=self._attempt_invasion)

    def on_unit_selection_changed(self, selected_units):
        """Called when user changes selection in the Unit Table."""
        if not self._is_human_interactive_turn():
            self.selected_units_for_movement = []
            self.neutral_warning_hexes = set()
            self.view.highlight_movement_range([])
            return
        if self.game_state.phase == GamePhase.COMBAT:
            # In combat, we manage selection manually via clicks,
            # but if the user interacts with the table directly, we respect it.
            pass
        else:
            self.selected_units_for_movement = selected_units

        # Clear highlights if no units selected
        if not selected_units and self.game_state.phase != GamePhase.COMBAT:
            self.view.highlight_movement_range([])
            self.neutral_warning_hexes = set()
            return

        if self.game_state.phase == GamePhase.MOVEMENT:
            # Only highlight if it's the active player's turn
            if any(u.allegiance != self.game_state.active_player for u in selected_units):
                self.view.highlight_movement_range([])
                self.neutral_warning_hexes = set()
                return

            movement_range = self.movement_service.get_reachable_hexes(selected_units)
            self.neutral_warning_hexes = set(movement_range.neutral_warning_coords)
            self.view.highlight_movement_range(
                movement_range.reachable_coords,
                movement_range.neutral_warning_coords
            )

        elif self.game_state.phase == GamePhase.COMBAT:
            # Visual refresh handled by handle_combat_click mostly
            pass

    def on_hex_clicked(self, hex_obj):
        """Called when user clicks a hex in Movement OR Combat phase."""
        if not self._is_human_interactive_turn():
            return
        if self.game_state.phase == GamePhase.MOVEMENT:
            if not self.selected_units_for_movement:
                return
            try:
                target = hex_obj.axial_to_offset()
                selected_ids = ", ".join(u.id for u in self.selected_units_for_movement)
                RuntimeDiagnostics.record_event(
                    f"Movement click: target={target} units=[{selected_ids}]"
                )
            except Exception:
                pass
            col, row = hex_obj.axial_to_offset()
            if (col, row) in self.neutral_warning_hexes:
                from PySide6.QtWidgets import QMessageBox
                decision = self.movement_service.invasion_handler.evaluate_neutral_entry(hex_obj)
                if not decision.is_neutral_entry:
                    pass
                elif decision.blocked_message:
                    QMessageBox.information(
                        self.view.window(),
                        "Neutral Territory",
                        decision.blocked_message
                    )
                    return
                elif decision.confirmation_prompt:
                    reply = QMessageBox.question(
                        self.view.window(),
                        "Neutral Territory",
                        decision.confirmation_prompt,
                        QMessageBox.Ok | QMessageBox.Cancel
                    )
                    if reply == QMessageBox.Ok:
                        self._attempt_invasion(decision.country_id or "unknown")
                    return

            # Move all selected units
            self.movement_service.push_movement_undo_snapshot()
            move_result = self.movement_service.move_units_to_hex(self.selected_units_for_movement, hex_obj)
            if move_result.errors:
                RuntimeDiagnostics.record_event(
                    f"Movement blocked: target={hex_obj.axial_to_offset()} errors={move_result.errors}"
                )
                self.movement_service.discard_last_movement_snapshot()
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.view.window(),
                    "Move Blocked",
                    move_result.errors[0]
                )
                return
            RuntimeDiagnostics.record_event(
                f"Movement applied: target={hex_obj.axial_to_offset()} "
                f"moved={[u.id for u in move_result.moved]}"
            )

            # Clear selection/highlights
            self.view.highlight_movement_range([])
            # Defer redraw to avoid mutating the scene while click dispatch is active.
            self._schedule_deferred(self.view.sync_with_model)
            self._schedule_deferred(self._refresh_info_panel)
            moved_stack = list(self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r))
            self._schedule_deferred(lambda units=moved_stack: self.view.units_clicked.emit(units))
            self.selected_units_for_movement = []
            self.neutral_warning_hexes = set()

        elif self.game_state.phase == GamePhase.COMBAT:
            self.handle_combat_click(hex_obj)

    def handle_combat_click(self, target_hex):
        """Delegate combat click handling to the combat click handler.
        
        Args:
            target_hex: Hex object that was clicked during combat phase.
        """
        if self.combat_click_handler:
            self.combat_click_handler.handle_click(target_hex)

    def reset_combat_selection(self):
        """Clear any combat selection and target highlights."""
        if self.combat_click_handler:
            self.combat_click_handler.reset_selection()

    def _continue_automatic_phases(self):
        """
        Continue processing automatic phases after the current one completes.
        This method is called via QTimer.singleShot to avoid recursion.
        """
        # Clear the flag so the scheduled tick can run
        self._processing_automatic_phases = False
        # Process the next phase
        self.process_game_turn()

    def handle_country_activation(self, country_id, allegiance):
        """
        Handle country activation signal from diplomacy dialog.
        This method properly separates view from model manipulation.
        
        Args:
            country_id: ID of the country to activate
            allegiance: Allegiance to assign (highlord/whitestone)
        """
        if self.diplomacy_service.activate_country(country_id, allegiance):
            print(f"Country {self.translator.get_country_name(country_id)} activated for {allegiance} via controller")
            self._refresh_info_panel()
            self._refresh_minimap_allegiance()
        else:
            print(f"Country {self.translator.get_country_name(country_id)} not found for activation.")

    def handle_unit_deployment(self, unit, target_hex):
        """
        Handle unit deployment request from map view.
        
        Args:
            unit: Unit to deploy
            target_hex: Target hex for deployment
        """
        result = self.deployment_service.deploy_unit(
            unit,
            target_hex,
            invasion_deployment_active=self._invasion_deployment_active,
            invasion_deployment_allegiance=self._invasion_deployment_allegiance,
            invasion_deployment_country_id=self._invasion_deployment_country_id,
        )
        if not result.success:
            RuntimeDiagnostics.record_event(
                f"Deployment blocked: unit={TextFormatter.format_unit_log_string(unit)} target={target_hex.axial_to_offset()} error={result.error}"
            )
            print(result.error)
            return
        # Deployments originating from Strategic Events/Activation are reinforcement-only
        # for this turn and should not move immediately in the following movement step.
        if self.game_state.phase in {GamePhase.STRATEGIC_EVENTS, GamePhase.ACTIVATION}:
            if hasattr(unit, "movement_points"):
                unit.movement_points = 0
            if hasattr(unit, "moved_this_turn"):
                unit.moved_this_turn = True
        self._deployment_session_unit_ids.add(unit.id)
        RuntimeDiagnostics.record_event(
            f"Deployment applied: unit={TextFormatter.format_unit_log_string(unit)} target={target_hex.axial_to_offset()}"
        )
        
        # Sync the map on next tick; defer heavy dialog rebuild slightly to avoid
        # QWidget teardown/rebuild races right after deployment clicks.
        def _deferred_sync():
            self.view.sync_with_model()
            self._queue_replacements_dialog_refresh()
            # During deployment sessions, the minimap refresh is expensive and not required
            # for immediate interaction correctness.
            if not self._is_replacements_dialog_visible():
                self._refresh_info_panel()
        self._schedule_deferred(_deferred_sync)
        
        print(f"Unit {TextFormatter.format_unit_log_string(unit)} deployed to {target_hex.axial_to_offset()} via controller")

    def _queue_replacements_dialog_refresh(self):
        """Queue a refresh of the replacements dialog, avoiding rapid repeated updates.
        
        Prevents dialog rebuild races and throttles refresh calls.
        """
        dlg = self.replacements_dialog
        if not (dlg and shiboken6.isValid(dlg) and dlg.isVisible()):
            return
        if self._replacements_refresh_queued:
            return
        self._replacements_refresh_queued = True

        def _do_refresh():
            self._replacements_refresh_queued = False
            current = self.replacements_dialog
            if not (current and shiboken6.isValid(current) and current.isVisible()):
                return
            if getattr(self.view, "deploying_unit", None) is not None:
                QTimer.singleShot(80, self._queue_replacements_dialog_refresh)
                return
            current.refresh()

        QTimer.singleShot(120, _do_refresh)

    def on_board_button_clicked(self):
        """Handles the (Un)Board button during Movement phase.
        Implements boarding algorithm: load armies into selected fleets and leaders into same ship.
        For unboarding: if selected units are transported, unboard them to the carrier hex.
        """
        if not self._is_human_interactive_turn():
            return
        # Only in Movement Phase
        if self.game_state.phase != GamePhase.MOVEMENT:
            print("(Un)Board action is only allowed during Movement phase.")
            return

        selected = self.selected_units_for_movement
        if not selected:
            return
        from PySide6.QtWidgets import QMessageBox
        decision = self.movement_service.invasion_handler.evaluate_unboard_neutral_entry(selected)
        if decision.is_neutral_entry:
            if decision.blocked_message:
                QMessageBox.information(
                    self.view.window(),
                    "Neutral Territory",
                    decision.blocked_message,
                )
                return
            if decision.confirmation_prompt:
                reply = QMessageBox.question(
                    self.view.window(),
                    "Neutral Territory",
                    decision.confirmation_prompt,
                    QMessageBox.Ok | QMessageBox.Cancel
                )
                if reply != QMessageBox.Ok:
                    return
                outcome = self._attempt_invasion(
                    decision.country_id or "unknown",
                    invasion_units=decision.invasion_units or [],
                )
                if not (outcome and outcome.success and outcome.winner == self.game_state.active_player):
                    return
        result = self.movement_service.handle_board_action(selected)
        if not result.handled:
            return
        for message in result.messages:
            print(message)
        if result.force_sync:
            anchor_hex = None
            for unit in selected:
                host = getattr(unit, "transport_host", None)
                base = host if host is not None else unit
                pos = getattr(base, "position", None)
                if pos and None not in pos:
                    anchor_hex = Hex.offset_to_axial(*pos)
                    break
            # Selection can contain now-stale transport relationships after (Un)Board.
            # Reset it before syncing to avoid acting on outdated references.
            self.selected_units_for_movement = []
            self.neutral_warning_hexes = set()
            self.view.highlight_movement_range([])
            self._schedule_deferred(self.view.sync_with_model)
            self._schedule_deferred(self._refresh_info_panel)
            if anchor_hex is not None:
                stack_units = list(self.game_state.map.get_units_in_hex(anchor_hex.q, anchor_hex.r))
                self._schedule_deferred(lambda units=stack_units: self.view.units_clicked.emit(units))
            else:
                self._schedule_deferred(lambda: self.view.units_clicked.emit([]))

    def _handle_deployment_from_event(self, effects, active_player):
        """
        Helper method to handle deployment UI after strategic events or activation.
        
        Args:
            effects: Dictionary containing event effects (alliance, add_units, etc.)
            active_player: The player who triggered this deployment
        """
        from src.gui.replacements_dialog import ReplacementsDialog
        from PySide6.QtWidgets import QMessageBox

        deployment_plan = self.diplomacy_service.build_deployment_plan(effects, active_player)
        self._refresh_minimap_allegiance()

        # Stop timer so loop waits for user
        self.ai_timer.stop()
        self._pending_phase_advance_after_deployment = True

        # Open Deployment Window
        self.replacements_dialog = ReplacementsDialog(self.game_state, self.view,
                                                      parent=self.view.window(),
                                                      filter_country_id=deployment_plan.country_filter,
                                                      allow_territory_deploy=True)
        self._connect_replacements_dialog_signals()
        self.replacements_dialog.show()
        self._begin_deployment_session()

        QMessageBox.information(
            self.replacements_dialog,
            deployment_plan.message_title,
            deployment_plan.message_text
            + "\nClick 'Minimize' to interact with map.\n"
            "Click 'End Turn' (End Phase) when finished.",
        )

    def _connect_replacements_dialog_signals(self):
        """Connect replacements dialog signals to controller slots.
        
        Uses UniqueConnection to prevent duplicate signal connections.
        """
        dlg = self.replacements_dialog
        if not (dlg and shiboken6.isValid(dlg)):
            return
        for sig, slot in (
            (dlg.conscription_requested, self.on_conscription_requested),
            (dlg.ready_unit_clicked, self.on_ready_unit_clicked),
            (dlg.finish_deployment_clicked, self.on_finish_deployment_clicked),
        ):
            sig.connect(slot, Qt.UniqueConnection)

    def on_conscription_requested(self, kept_unit, discarded_unit):
        """Handle conscription request from the replacements dialog.
        
        Args:
            kept_unit: Unit to keep after conscription.
            discarded_unit: Unit to discard during conscription.
        """
        self.game_state.apply_conscription(kept_unit, discarded_unit)
        if self._is_replacements_dialog_visible():
            self.replacements_dialog.refresh()

    def on_depleted_merge_requested(self, unit1, unit2):
        """
        Resolve depleted-stack merge decision in controller (MVC-safe):
        chosen unit -> ACTIVE, other -> RESERVE off-map.
        """
        from src.gui.replacements_dialog import UnitSelectionDialog

        dlg = UnitSelectionDialog(unit1, unit2, self.view.window())
        dlg.setWindowTitle("Reinforce Unit")
        if dlg.exec():
            kept_unit = dlg.selected_unit
            discarded_unit = dlg.discarded_unit

            if kept_unit:
                kept_unit.status = UnitState.ACTIVE
            if discarded_unit:
                self.game_state.movement_service.remove_unit_from_board(
                    discarded_unit,
                    escaped=False,
                    clear_transport=True,
                    clear_river_hexside=True,
                    remove_passengers=True,
                )
                discarded_unit.status = UnitState.RESERVE

            self.view.sync_with_model()
            self._refresh_info_panel()

    def on_asset_assign_requested(self, asset, unit):
        """Handle request to assign an asset to a unit (human player only).
        
        Args:
            asset: Asset object to assign.
            unit: Unit to assign the asset to.
        """
        if self.game_state.current_player and self.game_state.current_player.is_ai:
            return
        if not asset or not unit:
            return
        if hasattr(asset, "apply_to"):
            asset.apply_to(unit, on_assign_callback=self._on_asset_assigned)

    def on_asset_remove_requested(self, asset, unit):
        """Handle request to remove an asset from a unit (human player only).
        
        Args:
            asset: Asset object to remove.
            unit: Unit to remove the asset from.
        """
        if self.game_state.current_player and self.game_state.current_player.is_ai:
            return
        if not asset or not unit:
            return
        if hasattr(asset, "remove_from"):
            asset.remove_from(unit)
        self._refresh_assets_tab()

    def _on_asset_assigned(self, asset):
        """Callback invoked after an asset is assigned to a unit."""
        self._refresh_assets_tab()

    def _refresh_assets_tab(self):
        """Refresh the assets tab and update the info panel."""
        main_window = self.view.window()
        if hasattr(main_window, "assets_tab"):
            main_window.assets_tab.refresh()
            main_window.assets_tab.details_panel.update_buttons_state(None)
        self._refresh_info_panel()

    def on_ready_unit_clicked(self, unit, allow_territory_deploy):
        """Handle click on a ready (undeployed) unit in the replacements dialog.
        
        Highlights valid deployment hexes for the selected unit.
        
        Args:
            unit: Unit object that was clicked.
            allow_territory_deploy: Whether territory-wide deployment is allowed.
        """
        # Ignore stale clicks from a dialog row that no longer represents a deployable unit.
        if unit.status != UnitState.READY or unit.is_on_map:
            self.view.clear_highlights()
            return
        valid_hexes = self.deployment_service.get_valid_deployment_hexes(
            unit,
            allow_territory_wide=allow_territory_deploy
        )
        if not valid_hexes:
            self.view.clear_highlights()
            return
        self.view.highlight_deployment_targets(valid_hexes, unit)

    def on_finish_deployment_clicked(self):
        """Handle finish deployment button click, closing dialog and advancing phase.
        
        Special handling for invasion deployments to return to the main turn flow.
        """
        if not self._invasion_deployment_active:
            if self._is_replacements_dialog_visible():
                self.replacements_dialog.close()
                self.replacements_dialog = None
            self._end_deployment_session()
            if self._pending_phase_advance_after_deployment:
                self._pending_phase_advance_after_deployment = False
                self.game_state.advance_phase()
                self._schedule_deferred(self.process_game_turn)
            return

        if self._is_replacements_dialog_visible():
            self.replacements_dialog.close()
            self.replacements_dialog = None
        self._end_deployment_session()
        self._pending_phase_advance_after_deployment = False
        self._invasion_deployment_active = False
        self._invasion_deployment_country_id = None
        self._invasion_deployment_allegiance = None
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.view.highlight_movement_range([])
        self.view.sync_with_model()
        self._refresh_info_panel()
        self._refresh_turn_panel()
        self.connect_map_view_signals()
        self.check_active_player()
        if self.game_state.current_player and self.game_state.current_player.is_ai:
            self._schedule_deferred(self.process_game_turn)

    def _attempt_invasion(self, country_id, invasion_units=None):
        """Attempt to invade a neutral country and resolve the invasion.
        
        Args:
            country_id: ID of the country to invade.
            invasion_units: Optional list of units to include in the invasion force.
            
        Returns:
            Invasion outcome object with success status, winner, and messages.
        """
        from PySide6.QtWidgets import QMessageBox

        invasion_data = self.movement_service.get_invasion_force(country_id, extra_units=invasion_units)
        outcome = self.diplomacy_service.resolve_invasion(country_id, invasion_data)
        QMessageBox.information(self.view.window(), outcome.title, outcome.message)
        if outcome.success and outcome.winner:
            # Invasion creates a new checkpoint: previous movement undo is no longer allowed.
            self.movement_service.clear_movement_undo()
            self._start_invasion_deployment(country_id, outcome.winner)
        return outcome

    def on_undo_clicked(self):
        """Handle undo button click during movement phase to undo last movement."""
        if not self._is_human_interactive_turn():
            return
        if self.game_state.phase != GamePhase.MOVEMENT:
            return
        if not self.movement_service.undo_last_movement():
            return
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.view.highlight_movement_range([])
        self.view.sync_with_model()
        self._refresh_info_panel()

    def _start_invasion_deployment(self, country_id, allegiance):
        """Initiate deployment phase after a successful invasion.
        
        Handles AI auto-deployment or opens deployment dialog for human players.
        
        Args:
            country_id: ID of the invaded country.
            allegiance: Allegiance of the invasion winner.
        """
        from PySide6.QtWidgets import QMessageBox
        from src.gui.replacements_dialog import ReplacementsDialog

        winner_player = self.game_state.players.get(allegiance)
        winner_is_ai = bool(winner_player and winner_player.is_ai)

        # If the invasion winner is AI-controlled, auto-deploy immediately.
        if winner_is_ai:
            deployed = self.ai_baseline.deploy_all_ready_units(
                allegiance,
                allow_territory_wide=True,
                country_filter=country_id,
                invasion_deployment_active=True,
                invasion_deployment_allegiance=allegiance,
                invasion_deployment_country_id=country_id,
            )
            self._invasion_deployment_active = False
            self._invasion_deployment_country_id = None
            self._invasion_deployment_allegiance = None
            self._end_deployment_session()
            self.view.sync_with_model()
            self._refresh_info_panel()
            QMessageBox.information(
                self.view.window(),
                "Invasion Deployment",
                f"{country_id.title()} is AI-controlled. Auto-deployed units: {deployed}.",
            )
            return

        self._invasion_deployment_active = True
        self._invasion_deployment_country_id = country_id
        self._invasion_deployment_allegiance = allegiance
        self.ai_timer.stop()

        if self.replacements_dialog and shiboken6.isValid(self.replacements_dialog):
            self.replacements_dialog.close()
            self.replacements_dialog = None

        self.replacements_dialog = ReplacementsDialog(
            self.game_state,
            self.view,
            parent=self.view.window(),
            filter_country_id=country_id,
            allow_territory_deploy=True,
            invasion_mode=True
        )
        self._connect_replacements_dialog_signals()
        self.replacements_dialog.show()
        self._begin_deployment_session()

        message = (
            f"Deploy units for {country_id.title()}.\n"
            "Click 'End Phase' when finished to return to the current turn."
        )
        if allegiance == HL:
            message += "\nNewly deployed units cannot move this turn."

        QMessageBox.information(self.replacements_dialog, "Invasion Deployment", message)

