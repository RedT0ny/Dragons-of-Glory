# Conceptual example for game flow
from PySide6.QtCore import QObject, QTimer
from src.content.specs import GamePhase

class GameController(QObject):
    def __init__(self, game_state, view, highlord_ai=False, whitestone_ai=False):
        super().__init__()
        self.game_state = game_state
        self.view = view
        self.replacements_dialog = None

        # Configuration: True if Computer, False if Human
        self.ai_config = {
            "Highlord": highlord_ai,
            "Whitestone": whitestone_ai
        }

        # Timer to drive AI actions periodically
        self.ai_timer = QTimer()
        self.ai_timer.timeout.connect(self.process_game_turn)
        self.ai_timer.setInterval(1000) # 1 second between AI moves

    def start_game(self):
        """Initializes the loop and immediately processes the first phase."""
        self.process_game_turn()

    def check_active_player(self):
        """Checks if the loop should continue running automatically."""
        current_phase = self.game_state.phase
        current_side = self.game_state.active_player

        # Fix 2: Identify "System" phases that run automatically regardless of Human/AI
        # REPLACEMENTS, MOVEMENT, and COMBAT are 'Interactive', others are 'Automatic'
        system_phases = [
            GamePhase.STRATEGIC_EVENTS,
            GamePhase.ACTIVATION,
            GamePhase.INITIATIVE
        ]

        is_ai = self.ai_config.get(current_side, False)
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
        # 1. AI analyzes the game_state
        # 2. AI decides what to do next
        # 3. AI calls game_state methods to update state
        # 4. GUI updates automatically via sync_with_model()
        current_phase = self.game_state.phase
        active_player = self.game_state.active_player
        is_ai = self.ai_config.get(active_player, False)

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

        elif current_phase == GamePhase.STRATEGIC_EVENTS:
            # TODO: Draw random event
            print("Step 2: Strategic Events")
            self.game_state.advance_phase()

        elif current_phase == GamePhase.ACTIVATION:
            # TODO: Handle activation rolls
            print("Step 3: Activation")
            self.game_state.advance_phase()

        elif current_phase == GamePhase.INITIATIVE:
            # Logic: Roll Dice, determine winner
            import random
            hl_roll = random.randint(1, 4)
            ws_roll = random.randint(1, 4)
            # Simple tie-break logic needed (omitted for brevity)
            winner = "Highlord" if hl_roll >= ws_roll else "Whitestone"

            print(f"Step 4: Initiative. Winner: {winner}")
            self.game_state.set_initiative(winner)
            self.game_state.advance_phase()

        # Handle "Action" phases (Movement/Combat)
        elif current_phase == GamePhase.MOVEMENT:
            if is_ai:
                moved = self.execute_simple_ai_logic(active_player)
                if not moved: # AI is done moving
                    self.game_state.advance_phase()
            else:
                # For human: Wait for "End Phase" button click
                # The View should have a button connected to self.on_end_phase_clicked
                pass

        elif current_phase == GamePhase.COMBAT:
            if is_ai:
                # AI performs attacks
                self.game_state.advance_phase()
            else:
                # Wait for human to resolve combat and click "End Phase"
                pass

        self.view.sync_with_model()

        # If the new phase is AI controlled or automatic, keep the timer running/trigger next step
        self.check_active_player()

    def on_end_phase_clicked(self):
        """Call this when Human clicks 'End Phase' button."""
        # Close replacement dialog if open
        if self.replacements_dialog:
            self.replacements_dialog.close()
            self.replacements_dialog = None

        self.game_state.advance_phase()
        self.view.sync_with_model()

        # Check if we should auto-proceed to the next phase (e.g. Strategic Events)
        self.check_active_player()

    def execute_simple_ai_logic(self, side):
        # ... logic to call self.game_state relevant methods (move, attack...)
        return False # Return True if more moves are possible
