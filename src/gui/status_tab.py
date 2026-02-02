from PySide6.QtWidgets import QWidget, QHBoxLayout
from src.content.constants import WS, HL, NEUTRAL
from src.gui.unit_panel import AllegiancePanel

class StatusTab(QWidget):
    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self.init_ui()

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.refresh()

    def refresh(self):
        # Clear existing layout
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        columns = ["icon", "name", "status", "rating", "move", "pos"]

        # Create 3 panels
        self.main_layout.addWidget(AllegiancePanel(self.game_state, WS, columns, title="Whitestone"))
        self.main_layout.addWidget(AllegiancePanel(self.game_state, HL, columns, title="Highlord"))
        self.main_layout.addWidget(AllegiancePanel(self.game_state, NEUTRAL, columns, title="Neutral"))
