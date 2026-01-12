# Conceptual example for game flow
from PySide6.QtCore import QObject, QTimer

class GameController(QObject):
    def __init__(self, game_state, view, highlord_ai=False, whitestone_ai=False):
        super().__init__()
        self.game_state = game_state
        self.view = view

        # Configuration: True if Computer, False if Human
        self.ai_config = {
            "Highlord": highlord_ai,
            "Whitestone": whitestone_ai
        }

        # Timer to drive AI actions periodically
        self.ai_timer = QTimer()
        self.ai_timer.timeout.connect(self.process_ai_turn)
        self.ai_timer.setInterval(1000) # 1 second between AI moves

    def start_game(self):
        """Initializes the loop."""
        self.check_for_ai_turn()

    def check_for_ai_turn(self):
        current_side = self.game_state.current_turn_side
        if self.ai_config.get(current_side):
            self.ai_timer.start()
        else:
            # Wait for GUI signals/events from the user
            self.ai_timer.stop()

    def process_ai_turn(self):
        """Simulates one action for the current AI player."""
        # 1. AI analyzes the game_state
        # 2. AI decides on moves
        # 3. AI calls game_state.move_unit(...)
        # 4. GUI updates automatically via sync_with_model()
        current_side = self.game_state.current_turn_side

        # 1. Dummy AI logic: Find a unit and move it randomly
        # In a real scenario, this would call the AI logic module
        moved = self.execute_simple_ai_logic(current_side)

        # 2. Update the UI
        self.view.sync_with_model()

        # 3. If the AI is done with its phase, end turn and swap
        if not moved:
            self.game_state.end_phase()
            self.check_for_ai_turn()

    def execute_simple_ai_logic(self, side):
        # ... logic to call self.game_state.move_unit() ...
        return False # Return True if more moves are possible
