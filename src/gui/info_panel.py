from PySide6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QGridLayout, QPushButton, QHeaderView)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QIcon

from src.content.config import UNIT_ICON_SIZE
from src.content.specs import UnitColumn
from src.gui.unit_panel import UnitTable

class InfoPanel(QFrame):
    """The right-side panel for Unit and Hex info."""
    end_phase_clicked = Signal()
    selection_changed = Signal(list)

    def __init__(self, parent=None, game_state=None):
        """Sets up right panel with mini‑map and controls"""
        super().__init__(parent)
        self.game_state = game_state
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
        
        # Unit Info Frame
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

        # Unit Info table
        layout.addWidget(QLabel("Selected Units Stack:"))

        # Use reusable UnitTable
        self.units_table = UnitTable([
            UnitColumn.CHECKBOX,
            UnitColumn.ICON,
            UnitColumn.NAME,
            UnitColumn.RATING,
            UnitColumn.MOVE
        ])
        self.units_table.itemChanged.connect(self.on_item_changed)

        layout.addWidget(self.units_table)
        layout.addStretch()

        self.current_units = []

    def set_game_state(self, game_state):
        self.game_state = game_state

    @Slot(bool)
    def toggle_all_rows(self, checked):
        # Delegated to UnitTable mostly, but we need to notify selection
        self.units_table.toggle_all_rows(checked)
        self.notify_selection()

    @Slot(list)
    def update_unit_table(self, units):
        """Populates the table with the provided list of units."""
        self.current_units = units
        
        # Check for Movement Phase to auto-select
        from src.content.specs import GamePhase
        is_movement_phase = self.game_state and self.game_state.phase == GamePhase.MOVEMENT
        is_combat_phase = self.game_state and self.game_state.phase == GamePhase.COMBAT

        # Update table
        self.units_table.set_units(units, self.game_state)

        # Update checkboxes based on phase
        self.units_table.blockSignals(True)
        # Checkbox header state
        if hasattr(self.units_table, 'header_checkbox'):
            self.units_table.header_checkbox.isChecked = is_movement_phase or is_combat_phase
            self.units_table.header_checkbox.viewport().update()

        for row in range(self.units_table.rowCount()):
            item = self.units_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if is_movement_phase or is_combat_phase else Qt.Unchecked)
        self.units_table.blockSignals(False)

        # Immediately notify selection if we auto-selected units
        if is_movement_phase:
            self.notify_selection()

    def on_item_changed(self, item):
        if item.column() == 0:
            self.notify_selection()

    def notify_selection(self):
        selected = []
        for row in range(self.units_table.rowCount()):
            item = self.units_table.item(row, 0)
            if item.checkState() == Qt.Checked and row < len(self.current_units):
                selected.append(self.current_units[row])
        self.selection_changed.emit(selected)
