# Conceptual example for game flow
from PySide6.QtCore import QObject, QTimer
from time import monotonic

from src.content import loader
from src.content.config import CALENDAR_DATA
from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitState
from src.game.diplomacy import DiplomacyActivationService
from src.game.movement import MovementService
from src.game.ai_baseline import BaselineAIPlayer


class GameController(QObject):
    def __init__(
        self,
        game_state,
        view,
        highlord_ai=False,
        whitestone_ai=False,
        difficulty="normal",
        combat_details="brief",
    ):
        super().__init__()
        self.game_state = game_state
        self.view = view
        self.replacements_dialog = None
        self.difficulty = str(difficulty).strip().lower()
        self.combat_details = str(combat_details).strip().lower()
        self.game_state.difficulty = self.difficulty
        self.game_state.combat_details = self.combat_details

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
        self.movement_service = MovementService(self.game_state)
        self.deployment_service = self.game_state.deployment_service
        self._processing_automatic_phases = False  # Flag to prevent reentry
        self._map_view_signals_connected = False  # Track if map view signals are connected
        self.diplomacy_service = DiplomacyActivationService(self.game_state)
        self.ai_baseline = BaselineAIPlayer(self.game_state, self.movement_service, self.diplomacy_service)
        self._movement_undo_context = None
        self._calendar_by_turn = self._load_calendar()
        self._deferred_epoch = 0
        self._end_phase_transition_pending = False
        self._last_end_phase_request_at = 0.0
        self._deployment_session_unit_ids = set()
        self._victory_announced = False
        self._processing_turn_tick = False

    def get_runtime_config(self):
        return {
            "highlord_ai": bool(self.game_state.players.get(HL).is_ai) if HL in self.game_state.players else False,
            "whitestone_ai": bool(self.game_state.players.get(WS).is_ai) if WS in self.game_state.players else False,
            "difficulty": self.difficulty,
            "combat_details": self.combat_details,
        }

    def apply_runtime_config(self, config: dict):
        hl_ai = bool(config.get("highlord_ai", False))
        ws_ai = bool(config.get("whitestone_ai", False))
        self.difficulty = str(config.get("difficulty", self.difficulty)).strip().lower()
        self.combat_details = str(config.get("combat_details", self.combat_details)).strip().lower()
        self.game_state.difficulty = self.difficulty
        self.game_state.combat_details = self.combat_details

        if HL in self.game_state.players:
            self.game_state.players[HL].set_ai(hl_ai)
        if WS in self.game_state.players:
            self.game_state.players[WS].set_ai(ws_ai)

    def _schedule_deferred(self, callback):
        epoch = self._deferred_epoch
        QTimer.singleShot(0, lambda: self._run_deferred_if_current(epoch, callback))

    def _is_human_interactive_turn(self) -> bool:
        """
        True only when the active side is human and the phase expects direct input.
        """
        current_player = self.game_state.current_player
        if not current_player or current_player.is_ai:
            return False
        return self.game_state.phase in {GamePhase.DEPLOYMENT, GamePhase.REPLACEMENTS, GamePhase.MOVEMENT, GamePhase.COMBAT}

    def _run_deferred_if_current(self, epoch, callback):
        if epoch != self._deferred_epoch:
            return
        callback()

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
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.game_state.clear_movement_undo()
        if self.replacements_dialog:
            self.replacements_dialog.close()
            self.replacements_dialog = None
        if self.combat_click_handler:
            self.combat_click_handler.reset_selection()
        self.view.highlight_movement_range([])
        self._end_deployment_session()

    def _begin_deployment_session(self):
        self._deployment_session_unit_ids = set()

    def _end_deployment_session(self):
        self._deployment_session_unit_ids.clear()

    def _is_deployment_session_active(self):
        return bool(self.replacements_dialog and self.replacements_dialog.isVisible())

    def _can_redeploy_unit_now(self, unit):
        if not self._is_deployment_session_active():
            return False
        if getattr(self.view, "deploying_unit", None) is not None:
            return False
        if unit.id not in self._deployment_session_unit_ids:
            return False
        if unit.allegiance != self.game_state.active_player:
            return False
        if unit.status != UnitState.ACTIVE or not getattr(unit, "is_on_map", False):
            return False
        return True

    def on_map_units_clicked(self, clicked_units):
        """Allow redeploying units placed during the current deployment session."""
        if not self._is_human_interactive_turn():
            return
        if not clicked_units:
            return
        candidate = next((u for u in clicked_units if self._can_redeploy_unit_now(u)), None)
        if not candidate:
            return
        self._return_unit_to_ready_for_redeployment(candidate)

    def _return_unit_to_ready_for_redeployment(self, unit):
        if getattr(unit, "is_on_map", False):
            self.game_state.map.remove_unit_from_spatial_map(unit)
        unit.position = (None, None)
        unit.status = UnitState.READY
        if hasattr(unit, "movement_points"):
            unit.movement_points = unit.movement
        if hasattr(unit, "moved_this_turn"):
            unit.moved_this_turn = False
        if hasattr(unit, "attacked_this_turn"):
            unit.attacked_this_turn = False
        if hasattr(unit, "is_transported"):
            unit.is_transported = False
        if hasattr(unit, "transport_host"):
            unit.transport_host = None
        if hasattr(unit, "river_hexside"):
            unit.river_hexside = None

        def _deferred_redeploy_sync():
            if self.replacements_dialog and self.replacements_dialog.isVisible():
                self.replacements_dialog.refresh()
            self.view.sync_with_model()
            self._refresh_info_panel()
            if self.replacements_dialog and self.replacements_dialog.isVisible():
                self.on_ready_unit_clicked(unit, self.replacements_dialog.allow_territory_deploy)

        self._schedule_deferred(_deferred_redeploy_sync)
        print(f"Unit {unit.id} returned to READY for redeployment.")

    def _load_calendar(self):
        try:
            return loader.load_calendar_csv(CALENDAR_DATA)
        except Exception as exc:
            print(f"Failed to load calendar data: {exc}")
            return {}

    def start_game(self):
        """Initializes the loop and immediately processes the first phase."""
        self.process_game_turn()

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

            is_ai = False
            if self.game_state.current_player:
                is_ai = self.game_state.current_player.is_ai

            if current_phase == GamePhase.DEPLOYMENT:
                if is_ai:
                    deployed = self.ai_baseline.deploy_all_ready_units(active_player)
                    print(f"AI deployment complete. Deployed: {deployed}")
                    self.game_state.advance_phase()
                else:
                    if not self.replacements_dialog or not self.replacements_dialog.isVisible():
                        from src.gui.replacements_dialog import ReplacementsDialog
                        self.replacements_dialog = ReplacementsDialog(self.game_state, self.view, self.view)
                        self._connect_replacements_dialog_signals()
                        self.replacements_dialog.setWindowTitle(f"Deployment Phase - {active_player}")
                        self.replacements_dialog.show()
                        self._begin_deployment_session()
                print(f"Step 0: Deployment Phase - {active_player}")

            if current_phase == GamePhase.REPLACEMENTS:
                if is_ai:
                    conscriptions, deployed = self.ai_baseline.process_replacements(active_player)
                    print(f"AI replacements complete. Conscriptions: {conscriptions}, deployed: {deployed}")
                    self.game_state.advance_phase()
                else:
                    if not self.replacements_dialog or not self.replacements_dialog.isVisible():
                        from src.gui.replacements_dialog import ReplacementsDialog
                        self.replacements_dialog = ReplacementsDialog(self.game_state, self.view, self.view)
                        self._connect_replacements_dialog_signals()
                        self.replacements_dialog.show()
                        self._begin_deployment_session()
                print(f"Step 1: Replacements Phase - {active_player}")

            elif current_phase == GamePhase.STRATEGIC_EVENTS:
                print(f"Step 2: Strategic Events - {active_player}")
                event = self.game_state.draw_strategic_event(active_player)

                if event:
                    event.force_activate(self.game_state)
                    if not is_ai:
                        from src.gui.event_dialog import EventDialog
                        dlg = EventDialog(event)
                        dlg.exec()
                        effects = event.spec.effects
                        if "alliance" in effects or "add_units" in effects:
                            self._handle_deployment_from_event(effects, active_player)
                            self._refresh_turn_panel()
                            return
                        if event.spec.event_type == "artifact" or "grant_asset" in event.spec.effects:
                            asset_id = event.spec.effects.get("grant_asset")
                            self.open_assets_tab_for_assignment(asset_id)
                            self._refresh_turn_panel()
                            return

                if is_ai:
                    assigned = self.ai_baseline.assign_assets(active_player)
                    if assigned:
                        print(f"AI asset assignment complete. Assigned: {assigned}")
                self.game_state.advance_phase()

            elif current_phase == GamePhase.ACTIVATION:
                print(f"Step 3: Activation - {active_player}")
                if not self.game_state.has_neutral_countries():
                    print("No neutral countries remain. Skipping Activation phase.")
                    self.game_state.advance_phase()
                    self.view.sync_with_model()
                    self._refresh_info_panel()
                    self._refresh_turn_panel()
                    self.connect_map_view_signals()
                    self.check_active_player()
                    return
                if is_ai:
                    success, country_id = self.ai_baseline.perform_activation(active_player)
                    if success:
                        print(f"AI activated country {country_id}.")
                    else:
                        print("AI activation failed or skipped.")
                    self.game_state.advance_phase()
                    self.view.sync_with_model()
                    self._refresh_info_panel()
                    self._refresh_turn_panel()
                    self.connect_map_view_signals()
                    self.check_active_player()
                    return
                if not is_ai:
                    from src.gui.diplomacy_dialog import DiplomacyDialog
                    from PySide6.QtWidgets import QDialog
                    self.ai_timer.stop()
                    dlg = DiplomacyDialog(self.game_state, self.view.window())
                    dlg.country_activated.connect(self.handle_country_activation)
                    if dlg.exec() == QDialog.Accepted and dlg.activated_country_id:
                        country_id = dlg.activated_country_id
                        self._handle_deployment_from_event({"alliance": country_id, "alliance_already_activated": True}, active_player)
                        self._refresh_turn_panel()
                        return
                print("Activation attempt finished or skipped.")
                self.game_state.advance_phase()

            elif current_phase == GamePhase.INITIATIVE:
                import random
                hl_roll = random.randint(1, 4)
                ws_roll = random.randint(1, 4)
                if hl_roll == ws_roll:
                    winner = self.game_state.initiative_winner
                elif hl_roll > ws_roll:
                    winner = HL
                else:
                    winner = WS
                print(f"Step 4: Initiative. Winner: {winner}")
                self.game_state.set_initiative(winner)
                self.game_state.advance_phase()
                self._processing_automatic_phases = True
                try:
                    self._schedule_deferred(self._continue_automatic_phases)
                except Exception:
                    self._processing_automatic_phases = False
                    raise

            elif current_phase == GamePhase.MOVEMENT:
                print(f"Step 5: Movement phase - {active_player}")
                if is_ai:
                    assigned = self.ai_baseline.assign_assets(active_player)
                    if assigned:
                        print(f"AI asset assignment complete. Assigned: {assigned}")
                context = (self.game_state.turn, active_player, current_phase)
                if self._movement_undo_context != context:
                    self.game_state.clear_movement_undo()
                    self._movement_undo_context = context
                if is_ai:
                    moved = self.execute_simple_ai_logic(active_player)
                    if not moved:
                        self.game_state.advance_phase()

            elif current_phase == GamePhase.COMBAT:
                print(f"Step 6: Combat phase - {active_player}")
                if is_ai:
                    fought = self.ai_baseline.execute_best_combat(active_player)
                    if not fought:
                        self.game_state.advance_phase()

            self.view.sync_with_model()
            self._refresh_info_panel()
            self._refresh_turn_panel()
            self._announce_victory_if_needed()
            self.connect_map_view_signals()
            self.check_active_player()

            state_after = (self.game_state.phase, self.game_state.active_player)
            if state_after != state_before and not self.game_state.phase_manager.should_auto_advance():
                self._schedule_deferred(self.process_game_turn)
        finally:
            self._processing_turn_tick = False
    def _announce_victory_if_needed(self):
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
            main_window.info_panel.refresh()
            main_window.info_panel.set_undo_enabled(
                self.game_state.phase == GamePhase.MOVEMENT and self.game_state.can_undo_movement()
            )

    def _refresh_turn_panel(self):
        main_window = self.view.window()
        if not hasattr(main_window, "update_turn_panel"):
            return

        turn = self.game_state.turn
        calendar_spec = self._calendar_by_turn.get(turn)
        calendar_upper = calendar_spec.upper_label if calendar_spec else ""

        main_window.update_turn_panel(
            active_player=self.game_state.active_player,
            turn=turn,
            calendar_upper_label=calendar_upper,
            phase_label=self._format_phase_label(self.game_state.phase),
        )

    @staticmethod
    def _format_phase_label(phase):
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
                                "You may also manage other assets.\n"
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
            if self.replacements_dialog:
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
            self.game_state.clear_movement_undo()
            return

        # Drop repeated "End Phase" triggers until the queued phase transition is processed.
        if self._end_phase_transition_pending:
            return
        self._end_phase_transition_pending = True

        # Close replacement dialog if open
        if self.replacements_dialog:
            self.replacements_dialog.close()
            self.replacements_dialog = None
        self._end_deployment_session()

        # Clear movement highlights/selection
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.game_state.clear_movement_undo()
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
        return self.ai_baseline.execute_best_movement(side)

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
            col, row = hex_obj.axial_to_offset()
            if (col, row) in self.neutral_warning_hexes:
                from PySide6.QtWidgets import QMessageBox
                decision = self.movement_service.evaluate_neutral_entry(hex_obj)
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
            self.game_state.push_movement_undo_snapshot()
            move_result = self.movement_service.move_units_to_hex(self.selected_units_for_movement, hex_obj)
            if move_result.errors:
                self.game_state.discard_last_movement_snapshot()
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.view.window(),
                    "Move Blocked",
                    move_result.errors[0]
                )
                return

            # Clear selection/highlights
            self.view.highlight_movement_range([])
            # Defer redraw to avoid mutating the scene while click dispatch is active.
            self._schedule_deferred(self.view.sync_with_model)
            self._schedule_deferred(self._refresh_info_panel)
            self.selected_units_for_movement = []
            self.neutral_warning_hexes = set()

        elif self.game_state.phase == GamePhase.COMBAT:
            self.handle_combat_click(hex_obj)

    def handle_combat_click(self, target_hex):
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
            print(f"Country {country_id} activated for {allegiance} via controller")
        else:
            print(f"Country {country_id} not found for activation.")

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
            print(result.error)
            return
        self._deployment_session_unit_ids.add(unit.id)
        
        # Sync the view on the next event loop tick to avoid scene re-entrancy
        def _deferred_sync():
            if self.replacements_dialog and self.replacements_dialog.isVisible():
                self.replacements_dialog.refresh()
            self.view.sync_with_model()
            self._refresh_info_panel()
        self._schedule_deferred(_deferred_sync)
        
        print(f"Unit {unit.id} deployed to {target_hex.axial_to_offset()} via controller")

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
        result = self.movement_service.handle_board_action(selected)
        if not result.handled:
            return
        for message in result.messages:
            print(message)
        if result.force_sync:
            # Selection can contain now-stale transport relationships after (Un)Board.
            # Reset it before syncing to avoid acting on outdated references.
            self.selected_units_for_movement = []
            self.neutral_warning_hexes = set()
            self.view.highlight_movement_range([])
            self._schedule_deferred(self.view.sync_with_model)
            self._schedule_deferred(self._refresh_info_panel)

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

        # Stop timer so loop waits for user
        self.ai_timer.stop()

        # Open Deployment Window
        self.replacements_dialog = ReplacementsDialog(self.game_state, self.view,
                                                      parent=self.view,
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
        if not self.replacements_dialog:
            return
        self.replacements_dialog.conscription_requested.connect(self.on_conscription_requested)
        self.replacements_dialog.ready_unit_clicked.connect(self.on_ready_unit_clicked)
        self.replacements_dialog.finish_deployment_clicked.connect(self.on_finish_deployment_clicked)

    def on_conscription_requested(self, kept_unit, discarded_unit):
        self.game_state.apply_conscription(kept_unit, discarded_unit)
        if self.replacements_dialog:
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
                if getattr(discarded_unit, "is_on_map", False):
                    self.game_state.map.remove_unit_from_spatial_map(discarded_unit)
                discarded_unit.status = UnitState.RESERVE
                discarded_unit.position = (None, None)

            self.view.sync_with_model()
            self._refresh_info_panel()

    def on_asset_assign_requested(self, asset, unit):
        if self.game_state.current_player and self.game_state.current_player.is_ai:
            return
        if not asset or not unit:
            return
        if hasattr(asset, "apply_to"):
            asset.apply_to(unit)
        self._refresh_assets_tab()

    def on_asset_remove_requested(self, asset, unit):
        if self.game_state.current_player and self.game_state.current_player.is_ai:
            return
        if not asset or not unit:
            return
        if hasattr(asset, "remove_from"):
            asset.remove_from(unit)
        self._refresh_assets_tab()

    def _refresh_assets_tab(self):
        main_window = self.view.window()
        if hasattr(main_window, "assets_tab"):
            main_window.assets_tab.refresh()
            main_window.assets_tab.details_panel.update_buttons_state(None)
        self._refresh_info_panel()

    def on_ready_unit_clicked(self, unit, allow_territory_deploy):
        # Ignore stale clicks from a dialog row that no longer represents a deployable unit.
        if unit.status != UnitState.READY or getattr(unit, "is_on_map", False):
            self.view.clear_highlights()
            return
        valid_hexes = self.game_state.get_valid_deployment_hexes(
            unit,
            allow_territory_wide=allow_territory_deploy
        )
        if not valid_hexes:
            self.view.clear_highlights()
            return
        self.view.highlight_deployment_targets(valid_hexes, unit)

    def on_finish_deployment_clicked(self):
        if not self._invasion_deployment_active:
            if self.replacements_dialog:
                self.replacements_dialog.close()
                self.replacements_dialog = None
            self._end_deployment_session()
            return

        if self.replacements_dialog:
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

    def _attempt_invasion(self, country_id):
        from PySide6.QtWidgets import QMessageBox

        invasion_data = self.movement_service.get_invasion_force(country_id)
        outcome = self.diplomacy_service.resolve_invasion(country_id, invasion_data)
        QMessageBox.information(self.view.window(), outcome.title, outcome.message)
        if outcome.success and outcome.winner:
            # Invasion creates a new checkpoint: previous movement undo is no longer allowed.
            self.game_state.clear_movement_undo()
            self._start_invasion_deployment(country_id, outcome.winner)

    def on_undo_clicked(self):
        if not self._is_human_interactive_turn():
            return
        if self.game_state.phase != GamePhase.MOVEMENT:
            return
        if not self.game_state.undo_last_movement():
            return
        self.selected_units_for_movement = []
        self.neutral_warning_hexes = set()
        self.view.highlight_movement_range([])
        self.view.sync_with_model()
        self._refresh_info_panel()

    def _start_invasion_deployment(self, country_id, allegiance):
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

        if self.replacements_dialog:
            self.replacements_dialog.close()
            self.replacements_dialog = None

        self.replacements_dialog = ReplacementsDialog(
            self.game_state,
            self.view,
            parent=self.view,
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

