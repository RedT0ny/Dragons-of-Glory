# Conceptual example for game flow
from PySide6.QtCore import QObject, QTimer

from src.content.constants import HL, WS
from src.content.specs import GamePhase, UnitState, UnitType


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
        from src.game.combat import CombatClickHandler
        self.combat_click_handler = CombatClickHandler(self.game_state, self.view)
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
        def _deferred_end_phase_view_update():
            self.view.highlight_movement_range([])
            self.view.sync_with_model()
            self._refresh_info_panel()
        QTimer.singleShot(0, _deferred_end_phase_view_update)

        self.game_state.advance_phase()

        # Trigger the loop again to handle the next state immediately.
        # This ensures that if the next state is also Human-controlled (e.g., P2 Replacements),
        # the UI (Dialogs) for that player will be initialized.
        # Use QTimer.singleShot to avoid potential recursion issues
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
        if self.combat_click_handler:
            self.combat_click_handler.handle_click(target_hex)

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
        if not self.game_state.map.can_unit_land_on_hex(unit, target_hex):
            print(f"Cannot deploy {unit.id}: invalid terrain.")
            return
        if not self.game_state.map.can_stack_move_to([unit], target_hex):
            print(f"Cannot deploy {unit.id}: stacking limit or enemy presence.")
            return

        # Move the unit through the game state
        self.game_state.move_unit(unit, target_hex)
        
        # Update unit state
        unit.status = UnitState.ACTIVE
        
        # Sync the view on the next event loop tick to avoid scene re-entrancy
        def _deferred_sync():
            self.view.sync_with_model()
            self._refresh_info_panel()
        QTimer.singleShot(0, _deferred_sync)
        
        print(f"Unit {unit.id} deployed to {target_hex.axial_to_offset()} via controller")

    def on_board_button_clicked(self):
        """Handles the (Un)Board button during Movement phase.
        Implements boarding algorithm: load armies into selected fleets and leaders into same ship.
        For unboarding: if selected units are transported, unboard them to the carrier hex.
        """
        # Only in Movement Phase
        if self.game_state.phase != GamePhase.MOVEMENT:
            print("(Un)Board action is only allowed during Movement phase.")
            return

        selected = self.selected_units_for_movement
        if not selected:
            return

        # Separate fleets, armies, leaders
        fleets = [u for u in selected if u.unit_type == UnitType.FLEET or getattr(u, 'passengers', None) is not None]
        armies = [u for u in selected if u.is_army()]
        leaders = [u for u in selected if u.is_leader()]

        # If selection includes transported units, unboard them (only if carrier is in coastal hex)
        transported = [u for u in selected if getattr(u, 'transport_host', None) is not None]
        if transported:
            for u in transported:
                carrier = u.transport_host
                if not carrier or not carrier.position:
                    print(f"Cannot unboard {u.id}: carrier missing position")
                    continue
                from src.game.map import Hex
                carrier_hex = Hex.offset_to_axial(*carrier.position)
                if carrier.unit_type == UnitType.WING:
                    if not self.game_state.map.can_unit_land_on_hex(u, carrier_hex):
                        print(f"Cannot unboard {u.id}: destination terrain invalid for passenger")
                        continue
                else:
                    # Check carrier hex is coastal
                    if not self.game_state.map.is_coastal(carrier_hex):
                        print(f"Cannot unboard {u.id}: carrier not in coastal hex")
                        continue
                success = self.game_state.unboard_unit(u)
                if not success:
                    print(f"Failed to unboard {u.id} due to stacking or location.")
            self.view.sync_with_model()
            self._refresh_info_panel()
            return

        # Unboarding variant: Because transported units cannot be selected (they're removed from the spatial map),
        # we detect carriers (fleets/wings/citadels) among the selection that have passengers and attempt to
        # unboard their passengers if the carrier is in a coastal hex or in a port.
        from src.game.map import Hex
        from src.content.specs import LocType

        carriers_with_passengers = [u for u in selected if getattr(u, 'passengers', None) and len(u.passengers) > 0]
        if carriers_with_passengers:
            for carrier in carriers_with_passengers:
                if not carrier.position:
                    print(f"Carrier {carrier.id} has no position, skipping unboard.")
                    continue
                carrier_hex = Hex.offset_to_axial(*carrier.position)
                if carrier.unit_type == UnitType.WING:
                    for p in carrier.passengers[:]:
                        if not self.game_state.map.can_unit_land_on_hex(p, carrier_hex):
                            print(f"Cannot unboard {p.id} from {carrier.id}: destination terrain invalid")
                            continue
                        ok = self.game_state.unboard_unit(p)
                        if not ok:
                            print(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")
                    continue
                is_coastal = self.game_state.map.is_coastal(carrier_hex)
                loc = self.game_state.map.get_location(carrier_hex)
                is_port = False
                if loc and isinstance(loc, dict):
                    is_port = (loc.get('type') == LocType.PORT.value)

                if not (is_coastal or is_port):
                    print(f"Carrier {carrier.id} not in coastal hex or port, cannot unboard.")
                    continue

                # Unboard all passengers (copy list since unboard_unit mutates passengers)
                for p in carrier.passengers[:]:
                    ok = self.game_state.unboard_unit(p)
                    if not ok:
                        print(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")

                # Movement restriction: if carrier is in a coastal land hex (coastal but NOT port), it cannot move further this Turn
                if is_coastal and not is_port:
                    # Ensure movement_points exists
                    carrier.movement_points = 0

            self.view.sync_with_model()
            self._refresh_info_panel()
            return

        # Otherwise attempt boarding
        if not fleets:
            print("No fleet selected to board units into.")
            return

        # Algorithm: 1) Try to load every ground army into one selected fleet (one per fleet). Leaders load into same ships.
        # If there are more armies than fleets, remaining armies are not boarded.
        target_fleets = fleets[:]
        fi = 0
        for army in armies:
            if fi >= len(target_fleets):
                print(f"No more fleets to board army {army.id}.")
                break
            fleet = target_fleets[fi]
            if self.game_state.board_unit(fleet, army):
                print(f"Boarded army {army.id} onto {fleet.id}")
            else:
                print(f"Failed to board army {army.id} onto {fleet.id}")
            fi += 1

        # Load leaders into the first fleet selected (if any)
        if leaders and fleets:
            primary = fleets[0]
            for l in leaders:
                if self.game_state.board_unit(primary, l):
                    print(f"Boarded leader {l.id} onto {primary.id}")
                else:
                    print(f"Failed to board leader {l.id} onto {primary.id}")

        self.view.sync_with_model()
        self._refresh_info_panel()

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

