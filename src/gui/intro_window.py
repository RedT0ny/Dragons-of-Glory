import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QPushButton, 
                             QLabel, QHBoxLayout, QFrame, QSizePolicy, QFileDialog, QDialog)
from PySide6.QtGui import QPixmap, QFont, QAction, QMovie
from PySide6.QtCore import Qt, Signal
from src.content.config import COVER_PICTURE, APP_NAME, SAVEGAME_DIR, INTRO_VIDEO
from src.content.audio_manager import AudioManager
from src.gui.new_game_dialog import NewGameDialog
from src.gui.side_selection_dialog import SideSelectionDialog
from src.gui.volume_dialog import Ui_volumeDialog


class IntroWindow(QMainWindow):
    """
    The main menu / splash screen for Dragons of Glory.
    Provides options to start a new game, load, or exit.
    """
    # Signal emitted when the user successfully starts a new game configuration
    ready_to_start = Signal(object, dict) # (ScenarioSpec, player_config)
    # Signal emitted when a save file is selected
    ready_to_load = Signal(str) # (file_path)

    def __init__(self, translator):
        super().__init__()
        self.translator = translator
        self.setWindowTitle(APP_NAME)

        # 1. Fixed Resolution 1920x1080
        self.setFixedSize(1920, 1080)

        # 2. Main Container with Background
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Background Setup
        self.bg_label = QLabel(self.central_widget)
        self.bg_label.setGeometry(0, 0, 1920, 1080)
        self.movie = QMovie(INTRO_VIDEO)

        # 3. (Optional) Scale the movie to fit the screen
        # Note: Movies don't scale as easily as Pixmaps, so it's best if the
        # GIF is already 1920x1080. If not, we set the scaled size:
        self.movie.setScaledSize(self.bg_label.size())

        # 4. Assign the movie to the label and start it
        self.bg_label.setMovie(self.movie)
        self.movie.start()

        # 3. UI Layout Overlay
        self.setup_ui()

    def setup_ui(self):
        # Create a layout that sits on top of the image
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(100, 100, 100, 100) # Margin from edges

        # Spacer to push menu to the bottom
        main_layout.addStretch()

        # Menu Container (Bottom-Left)
        menu_container = QVBoxLayout()
        menu_container.setSpacing(20)

        # 4. Libra Font 48px Gold Options
        options = [
            ("menu_continue", self.on_continue),
            ("menu_new_game", self.on_new_game),
            ("menu_settings", self.on_settings),
            ("menu_quit", self.on_quit)
        ]

        style = """
            QPushButton {
                background-color: transparent;
                color: #D4AF37; /* Classic Gold */
                font-family: 'Libra';
                font-size: 48px;
                text-align: left;
                border: none;
                    padding: 5px 15px; /* Adds space for the shadow background */
                    border-radius: 5px;  /* Softens the edges of the shadow */
                }
                QPushButton:hover {
                    color: #FFD700; /* Bright Gold on hover */
                    background-color: rgba(0, 0, 0, 150); /* Dark semi-transparent shadow */
                }
        """

        for key, callback in options:
            btn = QPushButton(self.translator.get_text("intro", key))
            btn.setStyleSheet(style)
            btn.setCursor(Qt.PointingHandCursor)

            # FIX: Set the size policy so it doesn't expand horizontally
            # This makes the button only as wide as the text + padding
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

            btn.clicked.connect(callback)
            menu_container.addWidget(btn)

        # Optional: ensure the layout itself doesn't force expansion
        menu_container.setAlignment(Qt.AlignLeft)
        main_layout.addLayout(menu_container)

        # 5. Placeholder for Locale Flags (Bottom-Right corner)
        # (You can implement the flag QHBoxLayout here later)

    def on_continue(self):
        """Opens a file dialog to load a game."""
        save_dir = SAVEGAME_DIR
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        dialog = QFileDialog(self, self.translator.get_text("intro", "menu_continue"))
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setDirectory(save_dir)
        dialog.setNameFilter("Save Files (*.yaml *.yml *.json);;All Files (*)")
        # Avoid native Windows dialog COM/threading issues (0x8001010e).
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)

        if not dialog.exec():
            return

        files = dialog.selectedFiles()
        if files:
            file_path = files[0]
            print(f"Loading game from: {file_path}")
            # Emit a signal or call the controller to load the state
            self.ready_to_load.emit(file_path)

    def on_new_game(self):
        """Opens the Scenario Selection dialog."""
        sc_dialog = NewGameDialog(self, translator=self.translator)

        if sc_dialog.exec():
            spec = sc_dialog.get_selected_scenario_spec()
            if not spec:
                return

            # Chain to side selection
            side_dialog = SideSelectionDialog(self)
            if side_dialog.exec():
                player_config = side_dialog.get_player_config()

                print(f"Starting {spec.id}...")
                print(f"Config: {player_config}")

                # Finally, emit the signal to start the game
                self.ready_to_start.emit(spec, player_config)

    def on_settings(self):
        dialog = QDialog(self)
        ui = Ui_volumeDialog()
        ui.setupUi(dialog)

        audio_manager = AudioManager.from_app()
        if not audio_manager:
            dialog.exec()
            return

        initial_music_enabled = audio_manager.is_music_enabled()
        initial_sfx_enabled = audio_manager.is_sfx_enabled()
        initial_music_volume = audio_manager.get_music_volume_percent()
        initial_sfx_volume = audio_manager.get_sfx_volume_percent()

        ui.musicVolCbx.setChecked(initial_music_enabled)
        ui.sndVolCbx.setChecked(initial_sfx_enabled)
        ui.musicVolume.setValue(initial_music_volume)
        ui.soundVolume.setValue(initial_sfx_volume)
        ui.musicVolume.setEnabled(initial_music_enabled)
        ui.soundVolume.setEnabled(initial_sfx_enabled)

        def _on_music_toggle(checked):
            ui.musicVolume.setEnabled(checked)
            audio_manager.set_music_enabled(checked)

        def _on_sfx_toggle(checked):
            ui.soundVolume.setEnabled(checked)
            audio_manager.set_sfx_enabled(checked)

        ui.musicVolCbx.toggled.connect(_on_music_toggle)
        ui.sndVolCbx.toggled.connect(_on_sfx_toggle)
        ui.musicVolume.valueChanged.connect(audio_manager.set_music_volume_percent)
        ui.soundVolume.valueChanged.connect(audio_manager.set_sfx_volume_percent)

        def _restore_initial_audio():
            audio_manager.set_music_volume_percent(initial_music_volume)
            audio_manager.set_sfx_volume_percent(initial_sfx_volume)
            audio_manager.set_music_enabled(initial_music_enabled)
            audio_manager.set_sfx_enabled(initial_sfx_enabled)

        dialog.rejected.connect(_restore_initial_audio)
        dialog.exec()

    def on_quit(self):
        self.close()
