import sys
import locale
from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.game.game_state import GameState
from src.content.translator import Translator
from src.game.controller import GameController

def initialize_app():
    # Locale detection
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

    return app

def initialize_model():
    model = GameState()
    #model.load_scenario(None) # Logic encapsulated in GameState
    return model

def initialize_view(model: GameState):
    view= MainWindow(model)
    view.show()
    return view

def initialize_controller(model: GameState, view: MainWindow):
    # For Playtesting CVSC: Set both to True
    # For Human vs AI: Set one to False
    controller = GameController(
        game_state=model,
        view=view.map_view,
        highlord_ai=True,
        whitestone_ai=True
    )
    return controller

def main():

    # 1. Initialize application instance
    app = initialize_app()

    # 2. Initialize Model
    model = initialize_model()

    # 2. Initialize View
    view = initialize_view(model)

    # 3. Initialize Controller
    controller = initialize_controller(model, view)

    # Start the engine
    controller.start_game()

    # Start the event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main()