from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QFrame, QSizePolicy
from PySide6.QtGui import QPixmap, QFont, QAction
from PySide6.QtCore import Qt, Signal
from src.content.config import COVER_PICTURE, APP_NAME


class IntroWindow(QMainWindow):
    """
    The main menu / splash screen for Dragons of Glory.
    Provides options to start a new game, load, or exit.
    """
    # Signal emitted when the user successfully starts a new game configuration
    ready_to_start = Signal(object, dict) # (ScenarioSpec, player_config)

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
        pixmap = QPixmap(COVER_PICTURE)
        self.bg_label.setPixmap(pixmap.scaled(1920, 1080, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

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
        # Logic for Load Game dialog
        pass

    def on_new_game(self):
        # This will eventually trigger your Scenario Dialog
        print("Opening Scenario Selection...")
        # After selection, you would emit ready_to_start.emit(spec, config)
        # self.close()

    def on_settings(self):
        pass

    def on_quit(self):
        self.close()