import sys, locale, signal

#Enable faulthandler to get better crash diagnostics, especially for native code issues in PySide6
import faulthandler
faulthandler.enable(all_threads=True)
if hasattr(faulthandler, "register"):
    faulthandler.register(signal.SIGABRT, all_threads=True, chain=True)

from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.gui.intro_window import IntroWindow
from src.game.game_state import GameState
from src.content.translator import Translator
from src.game.controller import GameController



class GameApp:
    def __init__(self):
        self.app = self.initialize_app()
        self.translator = Translator(lang_code='en') # Or dynamic detection
        
        self.intro = IntroWindow(self.translator)
        self.intro.ready_to_start.connect(self.start_new_game)
        self.intro.ready_to_load.connect(self.load_existing_game)
        
        self.model = None
        self.view = None
        self.controller = None

    def initialize_app(self):
        # Locale detection
        try:
            user_locale = locale.getlocale(locale.LC_MESSAGES)[0]
        except (AttributeError, locale.Error):
            # Fallback if LC_MESSAGES isn't supported (e.g., on some Windows versions)
            user_locale = locale.getlocale()[0]

        # Extract the first two letters (e.g., 'en', 'es') or default to 'en'
        lang_code = user_locale[:2] if user_locale else 'en'

        print(f"Locale '{lang_code}' detected for translations.")

        # Initialize the Translator
        translator = Translator(lang_code=lang_code)

        # Create the application instance
        app = QApplication(sys.argv)
        return app

    def start_new_game(self, scenario_spec, player_config):
        """Initializes a fresh game from a scenario spec."""
        self.model = GameState()
        self.model.load_scenario(scenario_spec)
        self.launch_game_engine(player_config)

    def load_existing_game(self, file_path):
        """Initializes a game from a save file."""
        self.model = GameState()
        self.model.load_state(file_path)
        # For loaded games, we'll need a way to determine AI config, 
        # for now defaulting to human vs human or reading from save
        player_config = {"highlord_ai": False, "whitestone_ai": False}
        self.launch_game_engine(player_config)

    def launch_game_engine(self, player_config):
        """Common logic to show the main window and start the controller."""
        self.view = MainWindow(self.model)
        
        self.controller = GameController(
            game_state=self.model,
            view=self.view.map_view,
            highlord_ai=player_config.get("highlord_ai", False),
            whitestone_ai=player_config.get("whitestone_ai", False)
        )

        self.view.set_controller(self.controller)

        self.intro.close()
        self.view.showMaximized()
        self.controller.start_game()

    def run(self):
        self.intro.show()
        sys.exit(self.app.exec())

def main():
    game_app = GameApp()
    game_app.run()

if __name__ == "__main__":
    main()
