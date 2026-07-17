import sys, locale

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from src.content.config import GAME_ICON
from src.gui.main_window import MainWindow
from src.gui.intro_window import IntroWindow
from src.gui.loading_dialog import LoadingDialog
from src.game.game_state import GameState
from src.content.audio_manager import AudioManager
from src.content.translator import Translator
from src.content.runtime_diagnostics import RuntimeDiagnostics
from src.game.controller import GameController


class GameApp:
    def __init__(self):
        self.runtime_diagnostics = RuntimeDiagnostics()
        self.runtime_diagnostics.install()
        self.translator = Translator(lang_code='en')  # Or dynamic detection
        self.app = self.initialize_app()
        self.audio_manager = AudioManager()
        self.app.audio_manager = self.audio_manager

        self.intro = IntroWindow(self.translator)
        self.intro.ready_to_start.connect(self.start_new_game)
        self.intro.ready_to_load.connect(self.load_existing_game)
        self.audio_manager.play_intro_loop()

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
        self.translator = Translator(lang_code=lang_code)

        # Create the application instance
        app = QApplication(sys.argv)
        app.setWindowIcon(QIcon(GAME_ICON))
        return app

    def start_new_game(self, scenario_spec, player_config):
        """Initializes a fresh game from a scenario spec."""
        loading = LoadingDialog(None, "Starting New Game")
        try:
            loading.step("Creating game state...", 5)
            self.model = GameState()
            loading.step("Reading scenario data...", 25)
            self.model.load_scenario(scenario_spec)
            self.launch_game_engine(player_config, loading)
        except Exception:
            loading.close()
            raise

    def load_existing_game(self, file_path, player_config):
        """Initializes a game from a save file."""
        loading = LoadingDialog(None, "Loading Game")
        try:
            loading.step("Creating game state...", 5)
            self.model = GameState()
            loading.step("Reading saved game...", 25)
            self.model.load_state(file_path)
            self.launch_game_engine(player_config, loading)
        except Exception:
            loading.close()
            raise

    def launch_game_engine(self, player_config, loading=None):
        """Common logic to show the main window and start the controller."""
        if loading:
            loading.step("Setting up game window...", 50)
        self.view = MainWindow(self.model)

        if loading:
            loading.step("Creating controller...", 70)
        self.controller = GameController(
            game_state=self.model,
            view=self.view.map_view,
            highlord_ai=player_config.get("highlord_ai", False),
            whitestone_ai=player_config.get("whitestone_ai", False),
            difficulty=player_config.get("difficulty", "normal"),
            combat_details=player_config.get("combat_details", "brief"),
            supply=player_config.get("supply", "standard"),
            deployment=player_config.get("deployment", "canonical"),
            interception=player_config.get("interception", "disabled"),
        )

        if loading:
            loading.step("Setting up GUI...", 85)
        self.view.set_controller(self.controller)

        if loading:
            loading.step("Preparing turn engine...", 95)
        self.audio_manager.play_game_playlist()
        # Quiesce intro resources before processing gameplay phases.
        # This avoids UI lifecycle races when loading directly from intro.
        if self.intro is not None:
            try:
                if hasattr(self.intro, "movie") and self.intro.movie:
                    self.intro.movie.stop()
            except Exception:
                pass
            self.intro.hide()
            self.intro.close()
            self.intro.deleteLater()
            self.intro = None

        self.view.showMaximized()
        # Defer start one event-loop tick so window/layout/dialog parents are stable.
        if loading:
            self.controller.set_startup_loading_dialog(loading)
        QTimer.singleShot(0, self.controller.start_game)

    def run(self):
        self.intro.show()
        sys.exit(self.app.exec())


def main():
    game_app = GameApp()
    game_app.run()


if __name__ == "__main__":
    main()
