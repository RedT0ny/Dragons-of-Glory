import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QFrame, QTextEdit, QTabWidget, QLabel)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, Slot, QObject, Signal

from src.content.config import APP_NAME
from src.gui.map_view import AnsalonMapView
from src.gui.status_tab import StatusTab
from src.gui.assets_tab import AssetsTab
from src.gui.info_panel import InfoPanel

class ConsoleRedirector(QObject):
    """Custom stream object to redirect stdout/stderr to a Qt Signal while keeping original output."""
    text_written = Signal(str)

    def __init__(self, original_stream):
        super().__init__()
        self.original_stream = original_stream

    def write(self, text):
        # 1. Emit signal for the GUI log area
        self.text_written.emit(str(text))
        # 2. Write to the original python console stream
        self.original_stream.write(text)

    def flush(self):
        # Pass flush to original stream (required for file-like objects)
        self.original_stream.flush()


class MainWindow(QMainWindow):
    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self.setWindowTitle(APP_NAME)
        self.resize(1920, 1080)

        self.setup_menu_bar()

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Initialize Tab Widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- Tab 1: Map Tab ---
        self.map_tab = QWidget()
        map_layout = QHBoxLayout(self.map_tab)

        # Hex Map
        self.map_view = AnsalonMapView(self.game_state)
        self.map_view.zoom_on_show = 2
        map_layout.addWidget(self.map_view, stretch=4)

        # Sidebar
        self.info_panel = InfoPanel(game_state=self.game_state)
        map_layout.addWidget(self.info_panel, stretch=1)

        self.tabs.addTab(self.map_tab, "Map")

        self.status_tab = StatusTab(self.game_state)
        self.tabs.addTab(self.status_tab, "Status")

        # NEW ASSETS TAB
        self.assets_tab = AssetsTab(self.game_state)
        self.tabs.addTab(self.assets_tab, "Assets")

        # Placeholder (Heroes Registry)
        self.heroes_tab = QWidget()
        heroes_layout = QVBoxLayout(self.heroes_tab)
        heroes_layout.addWidget(QLabel("Heroes Registry"))
        self.tabs.addTab(self.heroes_tab, "Heroes")

        # Connect signals after all UI elements are initialized
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Game Log
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(100)
        self.log_area.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        main_layout.addWidget(self.log_area)

        # Redirect console output to the log area while keeping original console
        self.stdout_redirector = ConsoleRedirector(sys.stdout)
        self.stdout_redirector.text_written.connect(self.append_log)
        sys.stdout = self.stdout_redirector

        self.stderr_redirector = ConsoleRedirector(sys.stderr)
        self.stderr_redirector.text_written.connect(self.append_log)
        sys.stderr = self.stderr_redirector

        # Initialize visual grid from the game state
        self.map_view.sync_with_model()

        # Connect Map Selection to Info Panel
        self.map_view.units_clicked.connect(self.info_panel.update_unit_table)

    def on_tab_changed(self, index):
        if self.tabs.widget(index) == self.status_tab:
            self.status_tab.refresh()
        elif self.tabs.widget(index) == self.assets_tab:
            self.assets_tab.refresh()

    def setup_menu_bar(self):
        """Initializes the top menu bar."""
        menubar = self.menuBar()

        # --- Game Menu ---
        game_menu = menubar.addMenu("&Game")

        save_action = QAction("&Save Game", self)
        save_action.setShortcut("Ctrl+S")
        # save_action.triggered.connect(self.on_save_clicked)
        game_menu.addAction(save_action)

        load_action = QAction("&Load Game", self)
        load_action.setShortcut("Ctrl+L")
        game_menu.addAction(load_action)

        game_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        game_menu.addAction(exit_action)

        # --- View Menu ---
        view_menu = menubar.addMenu("&View")

        zoom_in_action = QAction("Zoom &In", self)
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.triggered.connect(lambda: self.map_view.scale(1.25, 1.25))
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QAction("Zoom &Out", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(lambda: self.map_view.scale(0.8, 0.8))
        view_menu.addAction(zoom_out_action)

        # --- Help Menu ---
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        help_menu.addAction(about_action)

    @Slot(str)
    def append_log(self, text):
        """Appends text to the log area and auto-scrolls to the bottom."""
        self.log_area.insertPlainText(text)
        # Scroll to the bottom automatically
        self.log_area.ensureCursorVisible()

    def set_controller(self, controller):
        """Connects UI signals to the controller."""
        self.info_panel.end_phase_clicked.connect(controller.on_end_phase_clicked)
        self.info_panel.selection_changed.connect(controller.on_unit_selection_changed)
        self.map_view.hex_clicked.connect(controller.on_hex_clicked)
        self.map_view.right_clicked.connect(controller.reset_combat_selection)