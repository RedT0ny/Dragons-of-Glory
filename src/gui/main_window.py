import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QFrame, QScrollArea, QGridLayout, QTextEdit)
from PySide6.QtCore import Qt, Signal, QObject, Slot

from src.content.config import APP_NAME
from src.gui.map_view import AnsalonMapView

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

class InfoPanel(QFrame):
    """The right-side panel for Unit and Hex info."""
    end_phase_clicked = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(350)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        
        layout = QVBoxLayout(self)
        
        # Mini-map placeholder
        self.mini_map = QLabel("Mini-map Area")
        self.mini_map.setFixedSize(320, 240)
        self.mini_map.setStyleSheet("background-color: #333; color: white;")
        self.mini_map.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.mini_map)
        
        # Control Buttons
        btn_grid = QGridLayout()
        btns = ["Move", "Attack", "Activate", "Prev", "Undo", "Combine", "Next", "Redo", "End Phase"]
        for i, name in enumerate(btns):
            btn = QPushButton(name)
            if name == "End Phase":
                btn.clicked.connect(self.end_phase_clicked.emit)
            btn_grid.addWidget(btn, i // 3, i % 3)
        layout.addLayout(btn_grid)
        
        # Selection Info
        self.selection_label = QLabel("Terrain (col, row)\nLocation (if any)")
        self.selection_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.selection_label)
        
        # Unit Info placeholder
        unit_box = QFrame()
        unit_box.setFrameStyle(QFrame.Box)
        unit_layout = QVBoxLayout(unit_box)
        unit_layout.addWidget(QLabel("Unit Name"), alignment=Qt.AlignCenter)
        unit_img = QLabel("Unit Picture")
        unit_img.setFixedSize(150, 150)
        unit_img.setStyleSheet("border: 1px solid black;")
        unit_layout.addWidget(unit_img, alignment=Qt.AlignCenter)
        unit_layout.addWidget(QLabel("Rating: X\nMov: remaining (total)\ncountry_name\nunit_status"))
        layout.addWidget(unit_box)
        
        layout.addStretch()

class MainWindow(QMainWindow):
    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self.setWindowTitle(APP_NAME)
        self.resize(1920, 1080)
        
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Content Layout (Map + Sidebar)
        content_layout = QHBoxLayout()
        
        # Hex Map
        self.map_view = AnsalonMapView(self.game_state)
        self.map_view.zoom_on_show = 2
        content_layout.addWidget(self.map_view, stretch=4)
    
        # Sidebar
        self.info_panel = InfoPanel()
        content_layout.addWidget(self.info_panel, stretch=1)
        
        main_layout.addLayout(content_layout)
        
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

    @Slot(str)
    def append_log(self, text):
        """Appends text to the log area and auto-scrolls to the bottom."""
        self.log_area.insertPlainText(text)
        # Scroll to the bottom automatically
        self.log_area.ensureCursorVisible()

    def set_controller(self, controller):
        """Connects UI signals to the controller."""
        self.info_panel.end_phase_clicked.connect(controller.on_end_phase_clicked)