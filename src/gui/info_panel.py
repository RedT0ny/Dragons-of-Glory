from PySide6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QGridLayout, QPushButton, QHeaderView, QGraphicsView)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QPointF
from PySide6.QtGui import QIcon, QColor

from src.content.config import UNIT_ICON_SIZE
from src.content.constants import HL, WS
from src.content.specs import UnitColumn
from src.gui.unit_panel import UnitTable
from src.gui.map_view import AnsalonMapView
from src.gui.map_items import HexagonItem

class MiniMapView(AnsalonMapView):
    """
    A zoomed-out, non-interactive view of the map for the info panel.
    Shows allegiance colors instead of specific country colors.
    """
    clicked = Signal(QPointF)

    def __init__(self, game_state, parent=None):
        super().__init__(game_state, parent, overlay_alpha=200) # Higher opacity for clear political view
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setInteractive(True) # Need to catch clicks
        self.zoom_on_show = 1.0 # Ensure it fits fully

    def wheelEvent(self, event):
        pass # Disable zooming

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.clicked.emit(scene_pos)
        # Do not call super() to avoid standard interactions (selection etc)

    def showEvent(self, event):
        """Ensure map is drawn and fitted when shown."""
        # Force sync if scene is empty
        if self.scene.itemsBoundingRect().isEmpty() and self.game_state and self.game_state.map:
            self.sync_with_model()

        # Call super which handles the delayed initial zoom
        super().showEvent(event)

    def draw_stack(self, stack, col, row):
        # Do not draw units on the mini-map
        pass

    def draw_static_map(self):
        super().draw_static_map()

        # Post-process to apply allegiance colors
        for item in self.scene.items():
            if isinstance(item, HexagonItem) and getattr(item, 'country_id', None):
                country = self.game_state.countries.get(item.country_id)
                if country:
                    new_color = None
                    if country.allegiance == HL:
                        new_color = QColor("red")
                    elif country.allegiance == WS:
                        new_color = QColor("blue")

                    if new_color:
                        # Update item color to reflect allegiance
                        rgba = QColor(new_color.red(), new_color.green(), new_color.blue(), self.overlay_alpha)
                        item.color = rgba
                        item.update()

class InfoPanel(QFrame):
    """The right-side panel for Unit and Hex info."""
    end_phase_clicked = Signal()
    selection_changed = Signal(list)
    minimap_clicked = Signal(QPointF)

    def __init__(self, parent=None, game_state=None):
        """Sets up right panel with mini‑map and controls"""
        super().__init__(parent)
        self.game_state = game_state
        self.setFixedWidth(350)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)

        layout = QVBoxLayout(self)

        # Mini-map
        self.mini_map = MiniMapView(self.game_state)
        self.mini_map.setFixedSize(320, 240)
        self.mini_map.clicked.connect(self.minimap_clicked.emit)
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

        # Sync minimap if game state is already populated
        if self.game_state and self.game_state.map:
            self.mini_map.sync_with_model()

    def set_game_state(self, game_state):
        self.game_state = game_state
        self.mini_map.game_state = game_state
        if self.game_state.map:
            self.mini_map.sync_with_model()

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
