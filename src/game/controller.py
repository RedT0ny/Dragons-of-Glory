# Conceptual example for game flow
from PySide6.QtCore import QObject, QTimer

from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitState


class GameController(QObject):
    def __init__(self, game_state, view, highlord_ai=False, whitestone_ai=False):
        super().__init__()
        self.game_state = game_state
        self.view = view
        self.replacements_dialog = None

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
        self.combat_attackers = []
        self._processing_automatic_phases = False  # Flag to prevent reentry
        self._map_view_signals_connected = False  # Track if map view signals are connected

    def start_game(self):
        """Initializes the loop and immediately processes the first phase."""
        self.process_game_turn()

    def check_active_player(self):
        """Checks if the loop should continue running automatically."""
        current_phase = self.game_state.phase

        # Use Player object to check AI status
        is_ai = False
        if self.game_state.current_player:
            is_ai = self.game_state.current_player.is_ai


        # Fix 2: Identify "System" phases that run automatically regardless of Human/AI
        # REPLACEMENTS, MOVEMENT, and COMBAT are 'Interactive', others are 'Automatic'
        system_phases = [
            GamePhase.STRATEGIC_EVENTS,
            GamePhase.ACTIVATION,
            GamePhase.INITIATIVE
        ]

        is_auto_phase = current_phase in system_phases

        # Start timer if it's an AI turn OR if the game needs to auto-resolve a phase
        if is_ai or is_auto_phase:
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
        # Prevent reentry to avoid infinite recursion
        if self._processing_automatic_phases:
            return
            
        # 1. AI analyzes the game_state
        # 2. AI decides what to do next
        # 3. AI calls game_state methods to update state
        # 4. GUI updates automatically via sync_with_model()
        current_phase = self.game_state.phase
        active_player = self.game_state.active_player

        is_ai = False
        if self.game_state.current_player:
            is_ai = self.game_state.current_player.is_ai

        if current_phase == GamePhase.DEPLOYMENT:
            if is_ai:
                print("AI is handling deployment...")
                self.game_state.advance_phase()
            else:
                # Open Replacements Dialog adapted for Deployment
                if not self.replacements_dialog or not self.replacements_dialog.isVisible():
                    from src.gui.replacements_dialog import ReplacementsDialog
                    self.replacements_dialog = ReplacementsDialog(self.game_state, self.view, self.view)
                    self.replacements_dialog.setWindowTitle(f"Deployment Phase - {active_player}")
                    self.replacements_dialog.show()
            print(f"Step 0: Deployment Phase - {active_player}")

        # Handle "Automatic" or "System" phases (Dice rolls, cards)
        if current_phase == GamePhase.REPLACEMENTS:
            if is_ai:
                # TODO: AI logic for replacements
                print("AI is handling replacements...")
                self.game_state.advance_phase()
            else:
                # Human Player
                if not self.replacements_dialog or not self.replacements_dialog.isVisible():
                    from src.gui.replacements_dialog import ReplacementsDialog
                    self.replacements_dialog = ReplacementsDialog(self.game_state, self.view,
                                                                  self.view)  # Parent to view
                    self.replacements_dialog.show()
                # We do NOT advance phase automatically.
                # User must click "End Phase" in main window (which calls on_end_phase_clicked)
            print(f"Step 1: Replacements Phase - {active_player}")

        elif current_phase == GamePhase.STRATEGIC_EVENTS:
            print(f"Step 2: Strategic Events - {active_player}")

            # Draw Event
            event = self.game_state.draw_strategic_event(active_player)

            if event:
                # Activate (update counts) and Apply Effects
                # We use force_activate because draw_strategic_event has already validated
                # that this event SHOULD happen (either via trigger or random draw).
                # Standard .activate() would fail for random events as they have no trigger condition.
                event.force_activate(self.game_state)

                if not is_ai:
                    # 1. Show Event Dialog
                    from src.gui.event_dialog import EventDialog
                    dlg = EventDialog(event)
                    dlg.exec()

                    effects = event.spec.effects

                    # 2. Check for Deployment Triggers (Alliance or Add Units)
                    if "alliance" in effects or "add_units" in effects:
                        self._handle_deployment_from_event(effects, active_player)
                        return

                    # 3. Check for Artifact/Assets
                    # "If the event is of the type artifact... open the assets_tab"
                    # Check "artifact" or specific event type enum if available
                    if event.spec.event_type == "artifact" or "grant_asset" in event.spec.effects:
                        asset_id = event.spec.effects.get("grant_asset")
                        self.open_assets_tab_for_assignment(asset_id)
                        return # Stop loop, wait for user interaction (End Turn)

            # If no event or event handled (and not requiring UI pause)
            self.game_state.advance_phase()

        elif current_phase == GamePhase.ACTIVATION:
            print(f"Step 3: Activation - {active_player}")
            if not is_ai:
                from src.gui.diplomacy_dialog import DiplomacyDialog
                from PySide6.QtWidgets import QDialog, QMessageBox

                dlg = DiplomacyDialog(self.game_state)
                # Connect signal before showing dialog
                dlg.country_activated.connect(self.handle_country_activation)
                
                # If player successfully activates a country
                if dlg.exec() == QDialog.Accepted and dlg.activated_country_id:
                    country_id = dlg.activated_country_id

                    # Use the same deployment handling method
                    self._handle_deployment_from_event({"alliance": country_id}, active_player)
                    return

                    # If AI, or human failed/cancelled activation, move on
            print("Activation attempt finished or skipped.")
            self.game_state.advance_phase()

        elif current_phase == GamePhase.INITIATIVE:
            # Logic: Roll Dice, determine winner
            import random
            hl_roll = random.randint(1, 4)
            ws_roll = random.randint(1, 4)
            # Simple tie-break logic needed (omitted for brevity)
            if hl_roll == ws_roll:
                # Ties go to the player who had initiative on the previous Turn
                winner = self.game_state.initiative_winner
            elif hl_roll > ws_roll:
                winner = HL
            else:
                winner = WS

            print(f"Step 4: Initiative. Winner: {winner}")
            self.game_state.set_initiative(winner)
            self.game_state.advance_phase()
            
            # For automatic phases, we need to continue processing the next phase
            # Set flag to indicate we're processing automatic phases
            self._processing_automatic_phases = True
            try:
                # Use QTimer.singleShot to avoid recursion
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._continue_automatic_phases)
            except Exception as e:
                self._processing_automatic_phases = False
                raise

        # Handle "Action" phases (Movement/Combat)
        elif current_phase == GamePhase.MOVEMENT:
            print(f"Step 5: Movement phase - {active_player}")
            if is_ai:
                moved = self.execute_simple_ai_logic(active_player)
                if not moved: # AI is done moving
                    self.game_state.advance_phase()
            else:
                # For human: Wait for "End Phase" button click
                # The View should have a button connected to self.on_end_phase_clicked
                pass

        elif current_phase == GamePhase.COMBAT:
            print(f"Step 6: Combat phase - {active_player}")
            if is_ai:
                # AI performs attacks
                self.game_state.advance_phase()
            else:
                # Wait for human to resolve combat and click "End Phase"
                pass

        self.view.sync_with_model()
        self._refresh_info_panel()
        
        # Connect map view signals if not already connected
        self.connect_map_view_signals()

        # If the new phase is AI controlled or automatic, keep the timer running/trigger next step
        self.check_active_player()

    def connect_map_view_signals(self):
        """Connect signals from map view to controller."""
        if not hasattr(self.view, 'unit_deployment_requested'):
            return
            
        if not self._map_view_signals_connected:
            self.view.unit_deployment_requested.connect(self.handle_unit_deployment)
            self._map_view_signals_connected = True
            print("Map view signals connected to controller")

    def _refresh_info_panel(self):
        """Helper to refresh side panel if accessible."""
        main_window = self.view.window()
        if hasattr(main_window, 'info_panel'):
            main_window.info_panel.refresh()

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
        # Close replacement dialog if open
        if self.replacements_dialog:
            self.replacements_dialog.close()
            self.replacements_dialog = None

        # Clear movement highlights/selection
        self.selected_units_for_movement = []
        self.view.highlight_movement_range([])

        self.game_state.advance_phase()
        self.view.sync_with_model()
        self._refresh_info_panel()

        # Trigger the loop again to handle the next state immediately.
        # This ensures that if the next state is also Human-controlled (e.g., P2 Replacements),
        # the UI (Dialogs) for that player will be initialized.
        # Use QTimer.singleShot to avoid potential recursion issues
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.process_game_turn)


    def execute_simple_ai_logic(self, side):
        # ... logic to call self.game_state relevant methods (move, attack...)
        return False # Return True if more moves are possible

    def on_unit_selection_changed(self, selected_units):
        """Called when user changes selection in the Unit Table."""
        if self.game_state.phase == GamePhase.COMBAT:
            # In combat, we manage selection manually via clicks,
            # but if the user interacts with the table directly, we respect it.
            pass
        else:
            self.selected_units_for_movement = selected_units

        # Clear highlights if no units selected
        if not selected_units and self.game_state.phase != GamePhase.COMBAT:
            self.view.highlight_movement_range([])
            return

        if self.game_state.phase == GamePhase.MOVEMENT:
            # Only highlight if it's the active player's turn
            if any(u.allegiance != self.game_state.active_player for u in selected_units):
                self.view.highlight_movement_range([])
                return

            reachable = self.calculate_reachable_hexes(selected_units)
            self.view.highlight_movement_range(reachable)

        elif self.game_state.phase == GamePhase.COMBAT:
            # Visual refresh handled by handle_combat_click mostly
            pass

    def on_hex_clicked(self, hex_obj):
        """Called when user clicks a hex in Movement OR Combat phase."""
        if self.game_state.phase == GamePhase.MOVEMENT:
            if not self.selected_units_for_movement:
                return

            # Move all selected units
            for unit in self.selected_units_for_movement:
                self.game_state.move_unit(unit, hex_obj)

            # Clear selection/highlights
            self.view.highlight_movement_range([])
            self.view.sync_with_model()
            self._refresh_info_panel()
            self.selected_units_for_movement = []

        elif self.game_state.phase == GamePhase.COMBAT:
            self.handle_combat_click(hex_obj)

    def handle_combat_click(self, target_hex):
        """
        Complex state machine for Combat Phase selection.
        """
        units_at_hex = self.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
        active_player = self.game_state.active_player

        # Identify what was clicked
        friendly_units = [u for u in units_at_hex if u.allegiance == active_player and not u.attacked_this_turn]
        enemy_units = [u for u in units_at_hex if u.allegiance != active_player and u.allegiance != 'neutral']

        # --- Scenario 2: Clicked Friendly Stack ---
        if friendly_units:
            # Check adjacency to EXISTING selection (if any)
            is_adjacent = False
            if self.combat_attackers:
                # Check if this new stack is adjacent to ANY of the currently selected units
                # (Actually, rule says "combine to make single attack against defender's hex")
                # So they must be adjacent to the SAME enemy, meaning they are likely neighbors
                # OR they share a common enemy neighbor.

                # Requirement: "Click on an adjacent stack" implies adjacent to current selection?
                # Or just "another stack that can attack the same target"?
                # Let's assume the user builds a group.

                # We add them to selection
                new_selection = list(set(self.combat_attackers + friendly_units))
            else:
                new_selection = friendly_units

            # Calculate common targets for this NEW proposed selection
            common_targets = self.calculate_common_targets(new_selection)

            if not common_targets:
                # Case 2b: "Turn possible targets to none" -> Refresh and show ONLY current stack
                self.combat_attackers = friendly_units
                # Recalculate targets for just this stack
                common_targets = self.calculate_common_targets(self.combat_attackers)
            else:
                # Case 2a: Valid combination
                self.combat_attackers = new_selection

            # Update UI
            self.view.units_clicked.emit(self.combat_attackers) # Update Table
            self.view.highlight_movement_range(common_targets) # Highlight targets
            # Also highlight the attackers themselves?
            # The view usually highlights targets (HexagonItems).
            # We might need a separate way to highlight UnitItems if desired, but table selection does that.
            return

        # --- Scenario 3, 4, 5: Clicked Enemy or Empty ---

        # Check if this hex is a Valid Target for the CURRENT selection
        current_targets = self.calculate_common_targets(self.combat_attackers)
        clicked_offset = target_hex.axial_to_offset()

        if clicked_offset in current_targets:
            # --- Scenario 5: Clicked a Possible Target ---
            from PySide6.QtWidgets import QMessageBox

            # Show Odds Dialog
            odds_str = self.calculate_odds_preview(self.combat_attackers, enemy_units, target_hex)

            reply = QMessageBox.question(
                None,
                "Confirm Attack",
                f"Attack with {len(self.combat_attackers)} units?\nOdds: {odds_str}",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.game_state.resolve_combat(self.combat_attackers, target_hex)
                # Mark attackers
                for u in self.combat_attackers:
                    u.attacked_this_turn = True

                # Clear all
                self.reset_combat_selection()
            return

        # If not a valid target...
        if enemy_units:
            # --- Scenario 3: Clicked Invalid Enemy ---
            # Clear and show only current stack? Wait, it's an enemy stack.
            # Requirement: "clicks on an hex with enemy units not possible targets. unit_table clears and shows only the current stack."
            # This phrasing is ambiguous. "shows only the current stack" usually refers to what was clicked.
            # But you can't select enemy stacks in the table usually.
            # I assume it means "Clear selection entirely" OR "Reset selection to nothing".
            self.reset_combat_selection()

        else:
            # --- Scenario 4: Clicked Empty Hex ---
            self.reset_combat_selection()

    def reset_combat_selection(self):
        self.combat_attackers = []
        self.view.highlight_movement_range([])
        self.view.units_clicked.emit([]) # Clear table

    def calculate_common_targets(self, attackers):
        """
        Returns list of (col, row) valid targets that ALL attacker stacks can attack.
        Actually, the rule is: "several stacks... can combine... against a defender's hex".
        This means the target hex must be adjacent to ALL participating stacks.
        """
        if not attackers:
            return []

        # Group attackers by location (Stack)
        from collections import defaultdict
        stacks = defaultdict(list)
        for u in attackers:
            if u.position:
                stacks[u.position].append(u)

        if not stacks:
            return []

        # Find valid targets for EACH stack
        stack_targets = []
        for pos, unit_list in stacks.items():
            # Get targets for this specific stack
            # A target is valid if it has enemies and is adjacent (and valid terrain)
            targets_for_this_stack = set(self.calculate_valid_targets(unit_list))
            stack_targets.append(targets_for_this_stack)

        # Find intersection
        if not stack_targets:
            return []

        common_set = set.intersection(*stack_targets)
        return list(common_set)

    def calculate_valid_targets(self, attackers):
        """Returns list of (col, row) tuples for valid attack targets."""
        if not attackers:
            return []

        # 1. Get all unique positions of attackers (usually they are in one stack, but could be multi-hex attack)
        attacker_hexes = set()
        for u in attackers:
            if u.position:
                from src.game.map import Hex
                attacker_hexes.add(Hex.offset_to_axial(*u.position))

        valid_target_offsets = set()

        # 2. Check neighbors of all attacker positions
        for start_hex in attacker_hexes:
            for next_hex in start_hex.neighbors():
                # Is there an enemy there?
                if self.game_state.map.has_enemy_army(next_hex, self.game_state.active_player):
                    # Validate "Move into" rule
                    if self.is_valid_attack_hex(attackers, start_hex, next_hex):
                        valid_target_offsets.add(next_hex.axial_to_offset())

        return list(valid_target_offsets)

    def is_valid_attack_hex(self, attackers, start_hex, target_hex):
        """
        Checks if specific units can attack across this hexside.
        """
        hexside = self.game_state.map.get_hexside(start_hex, target_hex)

        if hexside == "mountain":
            # Check if ALL attackers are capable
            for u in attackers:
                can_cross = u.unit_type == 'wing' or u.unit_type in ['dwarves', 'ogres']
                if not can_cross:
                    return False
        return True

    def calculate_odds_preview(self, attackers, defenders, hex_position):
        """Helper to just get the string "3:1" etc without rolling."""
        from src.game.combat import CombatResolver
        # We create a dummy resolver just to calc odds
        terrain = self.game_state.map.get_terrain(hex_position)
        resolver = CombatResolver(attackers, defenders, terrain)

        attacker_cs = sum(u.combat_rating for u in attackers)
        defender_cs = sum(u.combat_rating for u in defenders)
        return resolver.calculate_odds(attacker_cs, defender_cs)

    def calculate_reachable_hexes(self, units):
        """
        Delegates calculation of reachable hexes to the map model.
        Returns a list of (col, row) tuples.
        """
        reachable_hexes = self.game_state.map.get_reachable_hexes(units)
        return [h.axial_to_offset() for h in reachable_hexes]

    def _continue_automatic_phases(self):
        """
        Continue processing automatic phases after the current one completes.
        This method is called via QTimer.singleShot to avoid recursion.
        """
        try:
            # Process the next phase
            self.process_game_turn()
        finally:
            # Always reset the flag
            self._processing_automatic_phases = False

    def handle_country_activation(self, country_id, allegiance):
        """
        Handle country activation signal from diplomacy dialog.
        This method properly separates view from model manipulation.
        
        Args:
            country_id: ID of the country to activate
            allegiance: Allegiance to assign (highlord/whitestone)
        """
        # Activate the country through the game state
        self.game_state.activate_country(country_id, allegiance)
        print(f"Country {country_id} activated for {allegiance} via controller")

    def handle_unit_deployment(self, unit, target_hex):
        """
        Handle unit deployment request from map view.
        
        Args:
            unit: Unit to deploy
            target_hex: Target hex for deployment
        """
        # Move the unit through the game state
        self.game_state.move_unit(unit, target_hex)
        
        # Update unit state
        unit.status = UnitState.ACTIVE
        
        # Sync the view
        self.view.sync_with_model()
        self._refresh_info_panel()
        
        print(f"Unit {unit.id} deployed to {target_hex.axial_to_offset()} via controller")

    def _handle_deployment_from_event(self, effects, active_player):
        """
        Helper method to handle deployment UI after strategic events or activation.
        
        Args:
            effects: Dictionary containing event effects (alliance, add_units, etc.)
            active_player: The player who triggered this deployment
        """
        from src.gui.replacements_dialog import ReplacementsDialog
        from PySide6.QtWidgets import QMessageBox

        # Determine country filter
        country_filter = effects.get("alliance")
        
        # Activate country if alliance effect is present
        if "alliance" in effects:
            self.game_state.activate_country(country_filter, active_player)
        
        if "add_units" in effects:
            country_filter = None

        # Stop timer so loop waits for user
        self.ai_timer.stop()

        # Open Deployment Window
        self.replacements_dialog = ReplacementsDialog(self.game_state, self.view,
                                                      parent=self.view,
                                                      filter_country_id=country_filter,
                                                      allow_territory_deploy=True)
        self.replacements_dialog.show()

        # Instruction Popup
        msg_text = "Reinforcements have arrived!\n\nDeploy your new forces."
        if "alliance" in effects and "add_units" not in effects:
            msg_text = f"{effects['alliance'].title()} has joined the war!\n\nDeploy forces in their territory."

        QMessageBox.information(self.replacements_dialog, "Deployment",
                                msg_text + "\nClick 'Minimize' to interact with map.\n"
                                           "Click 'End Turn' (End Phase) when finished.")