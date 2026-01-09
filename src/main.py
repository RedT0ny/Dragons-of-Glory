import sys
import locale
from PySide6.QtWidgets import QApplication
from src.gui.main_window import MainWindow
from src.game.game_state import GameState
from src.content.translator import Translator

def main():
    # Modern approach: Try to get the user's preferred locale
    # This usually returns a tuple like ('en_US', 'UTF-8')
    try:
        user_locale = locale.getlocale(locale.LC_MESSAGES)[0]
    except (AttributeError, locale.Error):
        # Fallback if LC_MESSAGES isn't supported (e.g., on some Windows versions)
        user_locale = locale.getlocale()[0]

    # Extract the first two letters (e.g., 'en', 'es') or default to 'en'
    lang_code = user_locale[:2] if user_locale else 'en'

    # Initialize the Translator
    translator = Translator(lang_code=lang_code)

    # Create the application instance
    app = QApplication(sys.argv)
    app.setApplicationName(translator.get_text("general", "app_name"))

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