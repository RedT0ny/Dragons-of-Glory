import sys
from time import perf_counter
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QFrame, QTextEdit, QTabWidget, QLabel, QFileDialog, QMessageBox)
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtCore import Qt, Slot, QObject, Signal, QTimer

from src.content.config import APP_NAME, DEBUG
from src.gui.map_view import AnsalonMapView
from src.gui.status_tab import StatusTab
from src.gui.assets_tab import AssetsTab
from src.gui.info_panel import InfoPanel
from src.gui.unit_panel import UnitTable
from src.gui.turn_panel import TurnPanel


def _perf_print(message):
    if DEBUG:
        print(message)

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
        self.controller = None
        self._tab_switch_seq = 0
        self._tab_switch_started = {}
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

        # Bottom row: game log (left) + turn panel (right)
        self.bottom_row = QWidget()
        self.bottom_row.setFixedHeight(100)
        bottom_layout = QHBoxLayout(self.bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(100)
        self.log_area.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        bottom_layout.addWidget(self.log_area, stretch=1)

        self.turn_panel = TurnPanel(self.bottom_row)
        bottom_layout.addWidget(self.turn_panel, stretch=0, alignment=Qt.AlignRight)
        main_layout.addWidget(self.bottom_row)

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

        # Connect Hex Hover to Info Panel
        self.map_view.hex_hovered.connect(self.info_panel.update_hex_info)

        # Connect Mini-map click to Main Map center
        self.info_panel.minimap_clicked.connect(self.map_view.centerOn)

    def closeEvent(self, event: QCloseEvent):
        """Restores original console streams on exit to prevent segfaults."""
        # Restore original streams to avoid crash on shutdown (Access Violation 0xC0000005)
        # because Python might try to flush stdout/stderr to a destroyed QObject.
        if hasattr(self, 'stdout_redirector'):
            sys.stdout = self.stdout_redirector.original_stream
        if hasattr(self, 'stderr_redirector'):
            sys.stderr = self.stderr_redirector.original_stream

        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Handle WASD for map navigation."""
        # Define how many pixels to scroll per key press
        scroll_step = 50

        if event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
            if hasattr(self, 'info_panel'):
                self.info_panel.undo_clicked.emit()
            event.accept()
            return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if hasattr(self, 'info_panel'):
                self.info_panel.end_phase_clicked.emit()
            event.accept()
            return

        if event.key() == Qt.Key_W:
            self.map_view.verticalScrollBar().setValue(
                self.map_view.verticalScrollBar().value() - scroll_step
            )
        elif event.key() == Qt.Key_S:
            self.map_view.verticalScrollBar().setValue(
                self.map_view.verticalScrollBar().value() + scroll_step
            )
        elif event.key() == Qt.Key_A:
            self.map_view.horizontalScrollBar().setValue(
                self.map_view.horizontalScrollBar().value() - scroll_step
            )
        elif event.key() == Qt.Key_D:
            self.map_view.horizontalScrollBar().setValue(
                self.map_view.horizontalScrollBar().value() + scroll_step
            )
        else:
            # Pass other key events (like Ctrl+S) to the original handler
            super().keyPressEvent(event)

    def on_tab_changed(self, index):
        """Refreshes tab content when tab changes"""
        t0 = perf_counter()
        self._tab_switch_seq += 1
        seq = self._tab_switch_seq
        self._tab_switch_started[seq] = t0
        hits_before, misses_before = UnitTable.get_icon_cache_stats()
        tab_name = self.tabs.tabText(index)
        if self.tabs.widget(index) == self.status_tab:
            self.status_tab.refresh()
        elif self.tabs.widget(index) == self.assets_tab:
            self.assets_tab.refresh()
        dt_ms = (perf_counter() - t0) * 1000.0
        hits_after, misses_after = UnitTable.get_icon_cache_stats()
        _perf_print(
            f"[perf] MainWindow.on_tab_changed tab={tab_name} time_ms={dt_ms:.1f} "
            f"icon_hits={hits_after - hits_before} icon_misses={misses_after - misses_before}"
        )
        QTimer.singleShot(0, lambda s=seq, n=tab_name: self._log_tab_switch_settled(s, n))

    def _log_tab_switch_settled(self, seq, tab_name):
        t0 = self._tab_switch_started.pop(seq, None)
        if t0 is None:
            return
        total_ms = (perf_counter() - t0) * 1000.0
        _perf_print(f"[perf] MainWindow.tab_settled tab={tab_name} total_ms={total_ms:.1f}")

    def setup_menu_bar(self):
        """Initializes the top menu bar."""
        menubar = self.menuBar()

        # --- Game Menu ---
        game_menu = menubar.addMenu("&Game")

        save_action = QAction("&Save Game", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.on_save_clicked)
        game_menu.addAction(save_action)

        load_action = QAction("&Load Game", self)
        load_action.setShortcut("Ctrl+L")
        load_action.triggered.connect(self.on_load_clicked)
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
        self.controller = controller
        self.info_panel.end_phase_clicked.connect(controller.on_end_phase_clicked)
        self.info_panel.selection_changed.connect(controller.on_unit_selection_changed)
        self.info_panel.undo_clicked.connect(controller.on_undo_clicked)
        # Board/Unboard action (only active in Movement phase)
        if hasattr(self.info_panel, 'board_clicked'):
            self.info_panel.board_clicked.connect(getattr(controller, 'on_board_button_clicked', lambda: None))
        self.map_view.hex_clicked.connect(controller.on_hex_clicked)
        self.map_view.right_clicked.connect(controller.reset_combat_selection)

    def update_turn_panel(self, active_player: str, turn: int, calendar_upper_label: str, phase_label: str):
        if hasattr(self, "turn_panel") and self.turn_panel:
            self.turn_panel.update_state(
                active_player=active_player,
                turn=turn,
                calendar_upper_label=calendar_upper_label,
                phase_label=phase_label,
            )

    def on_save_clicked(self):
        dialog = QFileDialog(self, "Save Game")
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setFileMode(QFileDialog.AnyFile)
        dialog.setNameFilter("YAML Files (*.yaml *.yml);;All Files (*)")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return
        files = dialog.selectedFiles()
        if not files:
            return
        path = files[0]
        try:
            self.game_state.save_state(path)
            self.append_log(f"Game saved to {path}\n")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def on_load_clicked(self):
        dialog = QFileDialog(self, "Load Game")
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("YAML Files (*.yaml *.yml);;All Files (*)")
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return
        files = dialog.selectedFiles()
        if not files:
            return
        path = files[0]
        try:
            self.game_state.load_state(path)
            self.map_view.sync_with_model()
            self.info_panel.set_game_state(self.game_state)
            self.info_panel.refresh()
            self.status_tab.refresh()
            self.assets_tab.refresh()
            if self.controller:
                self.controller.process_game_turn()
            self.append_log(f"Game loaded from {path}\n")
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))
