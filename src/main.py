import sys
from PySide6.QtWidgets import QApplication
from src.gui.main_window import MainWindow
from src.game.game_state import GameState

def main():
    # Create the application instance
    app = QApplication(sys.argv)
    app.setApplicationName("Dragons of Glory")

    # Initialize the Model
    game_state = GameState()
    # You might want to call game_state.start_game() or load a scenario here later

    # Initialize the View with the Model
    window = MainWindow(game_state)
    window.show()

    # Start the event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()