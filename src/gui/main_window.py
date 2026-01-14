from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFrame, QScrollArea, QGridLayout)
from PySide6.QtCore import Qt

from src.content.config import APP_NAME
from src.gui.map_view import AnsalonMapView

class InfoPanel(QFrame):
    """The right-side panel for Unit and Hex info."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(250)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        
        layout = QVBoxLayout(self)
        
        # Mini-map placeholder
        self.mini_map = QLabel("Mini-map Area")
        self.mini_map.setFixedSize(230, 150)
        self.mini_map.setStyleSheet("background-color: #333; color: white;")
        self.mini_map.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.mini_map)
        
        # Control Buttons
        btn_grid = QGridLayout()
        btns = ["Move", "Attack", "Activate", "Prev", "Undo", "Combine", "Next", "Redo", "End Turn"]
        for i, name in enumerate(btns):
            btn_grid.addWidget(QPushButton(name), i // 3, i % 3)
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
        content_layout.addWidget(self.map_view, stretch=4)
    
        # Sidebar
        self.info_panel = InfoPanel()
        content_layout.addWidget(self.info_panel, stretch=1)
        
        main_layout.addLayout(content_layout)
        
        # Game Log
        self.log_area = QLabel("Game log...")
        self.log_area.setFixedHeight(100)
        self.log_area.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        main_layout.addWidget(self.log_area)

        # Initialize visual grid from the game state
        self.map_view.sync_with_model()
