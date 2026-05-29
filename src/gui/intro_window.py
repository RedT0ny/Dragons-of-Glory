import os
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QSizePolicy, QFileDialog, QDialog, QGraphicsScene, QGraphicsView
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtCore import QUrl, Qt, Signal
from src.content.config import APP_NAME, SAVEGAME_DIR, INTRO_VIDEO
from src.content.audio_manager import AudioManager
from src.gui.config_dialog import ConfigDialog
from src.gui.new_game_dialog import NewGameDialog
from src.gui.volume_dialog import Ui_volumeDialog


class IntroWindow(QMainWindow):
    """
    The main menu / splash screen for Dragons of Glory.
    Provides options to start a new game, load, or exit.
    """
    # Signal emitted when the user successfully starts a new game configuration
    ready_to_start = Signal(object, dict) # (ScenarioSpec, player_config)
    # Signal emitted when a save file and runtime configuration are selected
    ready_to_load = Signal(str, dict) # (file_path, player_config)

    def __init__(self, translator):
        super().__init__()
        self.translator = translator
        self.setWindowTitle(APP_NAME)

        # Fixed intro presentation size.
        self.setFixedSize(1600, 1080)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.video_view = QGraphicsView(self.central_widget)
        self.video_view.setGeometry(0, 0, 1600, 1080)
        self.video_view.setFrameShape(QGraphicsView.NoFrame)
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_view.setStyleSheet("background: black; border: 0;")

        self.video_scene = QGraphicsScene(self)
        self.video_view.setScene(self.video_scene)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setSize(self.video_view.size())
        self.video_scene.addItem(self.video_item)
        self.video_view.fitInView(self.video_item, Qt.IgnoreAspectRatio)

        self.overlay_widget = QWidget(self.central_widget)
        self.overlay_widget.setGeometry(0, 0, 1600, 1080)
        self.overlay_widget.setAttribute(Qt.WA_TranslucentBackground, True)

        self.video_player = QMediaPlayer(self)
        self.video_output = QAudioOutput(self)
        self.video_output.setVolume(0.0)

        self.video_player.setAudioOutput(self.video_output)
        self.video_player.setVideoOutput(self.video_item)
        self.video_player.setSource(QUrl.fromLocalFile(INTRO_VIDEO))
        self.video_player.mediaStatusChanged.connect(self._on_video_media_status_changed)
        self.video_player.play()

        self.setup_ui()

    def setup_ui(self):
        main_layout = QVBoxLayout(self.overlay_widget)
        main_layout.setContentsMargins(100, 100, 100, 100)

        main_layout.addStretch()

        menu_container = QVBoxLayout()
        menu_container.setSpacing(20)

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
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

            btn.clicked.connect(callback)
            menu_container.addWidget(btn)

        menu_container.setAlignment(Qt.AlignLeft)
        main_layout.addLayout(menu_container)

    def _on_video_media_status_changed(self, status):
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        self.video_player.setPosition(0)
        self.video_player.play()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = self.central_widget.size()
        self.video_view.setGeometry(0, 0, size.width(), size.height())
        self.overlay_widget.setGeometry(0, 0, size.width(), size.height())
        self.video_scene.setSceneRect(0, 0, size.width(), size.height())
        self.video_item.setSize(size)
        self.video_view.fitInView(self.video_item, Qt.IgnoreAspectRatio)

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
            config_dialog = ConfigDialog(self)
            config_dialog.set_from_config(
                {
                    "highlord_ai": False,
                    "whitestone_ai": False,
                    "difficulty": "normal",
                    "combat_details": "brief",
                    "supply": "standard",
                    "deployment": "canonical",
                }
            )
            if not config_dialog.exec():
                return
            player_config = config_dialog.get_config()
            print(f"Loading game from: {file_path}")
            print(f"Config: {player_config}")
            self.ready_to_load.emit(file_path, player_config)

    def on_new_game(self):
        """Opens the Scenario Selection dialog."""
        sc_dialog = NewGameDialog(self, translator=self.translator)

        if sc_dialog.exec():
            spec = sc_dialog.get_selected_scenario_spec()
            if not spec:
                return

            # Chain to side selection
            side_dialog = ConfigDialog(self)
            side_dialog.set_from_config(
                {
                    "highlord_ai": False,
                    "whitestone_ai": False,
                    "difficulty": "normal",
                    "combat_details": "brief",
                    "supply": "standard",
                    "deployment": "canonical",
                }
            )
            if side_dialog.exec():
                player_config = side_dialog.get_config()

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
