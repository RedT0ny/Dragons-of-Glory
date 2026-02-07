import os

from PySide6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QGridLayout, QPushButton, QHeaderView, QGraphicsView,
                               QSizePolicy)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QPointF
from PySide6.QtGui import QIcon, QColor, QPixmap, QFontDatabase, QFont

from src.content.config import UNIT_ICON_SIZE, IMAGES_DIR, FONTS_DIR, LIBRA_FONT
from src.content.constants import HL, WS
from src.content.specs import UnitColumn, UnitType
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
        self.update_allegiance_colors()

    def update_allegiance_colors(self):
        """Updates the colors of hexes based on current country allegiance."""
        if not self.game_state:
            return

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
                    else:
                        item.color = None

                    item.update()

    def sync_with_model(self):
        """Refreshes the view from the game state."""
        super().sync_with_model()
        self.update_allegiance_colors()


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
        btns = ["Prev", "Undo", "Combine", "Next", "Redo", "End Phase"]
        for i, name in enumerate(btns):
            btn = QPushButton(name)
            if name == "End Phase":
                btn.clicked.connect(self.end_phase_clicked.emit)
            btn_grid.addWidget(btn, i // 3, i % 3)
        layout.addLayout(btn_grid)
        
        # Selection Info
        self.selection_label = QLabel("Terrain (col, row)\nLocation (if any)")
        self.selection_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.selection_label)

        # Unit Info Frame
        self.unit_box = QFrame()
        self.unit_box.setFrameStyle(QFrame.Box)
        unit_layout = QVBoxLayout(self.unit_box)

        # 1. Picture
        self.lbl_unit_img = QLabel()
        self.lbl_unit_img.setFixedSize(250, 250)
        self.lbl_unit_img.setStyleSheet("border: 1px solid black; background-color: grey;")
        self.lbl_unit_img.setScaledContents(True)
        unit_layout.addWidget(self.lbl_unit_img, alignment=Qt.AlignCenter)

        # 2. Name (Libra Font)
        self.lbl_unit_name = QLabel("No Unit Selected")
        self.lbl_unit_name.setAlignment(Qt.AlignCenter)
        self._setup_libra_font()
        unit_layout.addWidget(self.lbl_unit_name)

        # 3. Stats Grid
        stats_grid = QGridLayout()
        # Rating
        stats_grid.addWidget(QLabel("Rating:"), 0, 0)
        self.lbl_rating = QLabel("-")
        stats_grid.addWidget(self.lbl_rating, 0, 1)

        # Movement
        stats_grid.addWidget(QLabel("Movement:"), 1, 0)
        self.lbl_movement = QLabel("-")
        stats_grid.addWidget(self.lbl_movement, 1, 1)

        # Status
        stats_grid.addWidget(QLabel("Status:"), 2, 0)
        self.lbl_status = QLabel("-")
        stats_grid.addWidget(self.lbl_status, 2, 1)

        # Allegiance
        stats_grid.addWidget(QLabel("Allegiance:"), 3, 0)
        self.lbl_allegiance = QLabel("-")
        stats_grid.addWidget(self.lbl_allegiance, 3, 1)

        # Equipment
        stats_grid.addWidget(QLabel("Equipment:"), 4, 0)
        self.lbl_equipment = QLabel("-")
        stats_grid.addWidget(self.lbl_equipment, 4, 1)

        # Terrain Affinity
        stats_grid.addWidget(QLabel("Affinity:"), 5, 0)
        self.lbl_terrain = QLabel("-")
        stats_grid.addWidget(self.lbl_terrain, 5, 1)

        unit_layout.addLayout(stats_grid)
        layout.addWidget(self.unit_box)

        # Unit Info table
        #layout.addWidget(QLabel("Selected Units Stack:"))

        # Use reusable UnitTable
        self.units_table = UnitTable([
            UnitColumn.CHECKBOX,
            UnitColumn.ICON,
            UnitColumn.NAME,
            UnitColumn.RATING,
            UnitColumn.MOVE
        ])
        self.units_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.units_table.setMinimumHeight(100)
        self.units_table.itemChanged.connect(self.on_item_changed)
        self.selection_changed.connect(self.update_unit_box)

        layout.addWidget(self.units_table)
        #layout.addStretch()

        self.current_units = []

        # Sync minimap if game state is already populated
        if self.game_state and self.game_state.map:
            self.mini_map.sync_with_model()

        # Initial update
        self.update_unit_box([])

    def refresh(self):
        """Manually refreshes the panel content (minimap, etc)."""
        if self.mini_map:
            self.mini_map.sync_with_model()

    @Slot(list)
    def update_unit_box(self, selected_units):
        if not selected_units:
            self.lbl_unit_name.setText("No Unit Selected")
            self.lbl_unit_img.clear()
            self.lbl_rating.setText("-")
            self.lbl_movement.setText("-")
            self.lbl_status.setText("-")
            self.lbl_allegiance.setText("-")
            self.lbl_equipment.setText("-")
            self.lbl_terrain.setText("-")
            return

        # Show info for the first selected unit
        unit = selected_units[0]

        # 1. Image
        img_name = unit.spec.picture if hasattr(unit.spec, 'picture') and unit.spec.picture else "army.jpg"
        img_path = os.path.join(IMAGES_DIR, img_name)
        if not os.path.exists(img_path):
            img_path = os.path.join(IMAGES_DIR, "army.jpg")

        if os.path.exists(img_path):
            self.lbl_unit_img.setPixmap(QPixmap(img_path))
        else:
            self.lbl_unit_img.setText("Img Not Found")

        # 2. Name
        self.lbl_unit_name.setText(str(unit.id))

        # 3. Rating
        # Tactical Rating (if Leader subclass), Combat Rating otherwise.
        if unit.is_leader():
            self.lbl_rating.setText(f"{unit.tactical_rating} (Tactical)")
        else:
            self.lbl_rating.setText(f"{unit.combat_rating} (Combat)")

        # 4. Movement: "Total (remaining)" -> Requirement: "Total (remaining)"
        # Note: logic in prompt said "Total (remaining)".
        # Usually it's Remaining / Total. Let's follow prompt exactly: "Total (remaining)"
        total = unit.movement
        remaining = getattr(unit, 'movement_points', total)
        self.lbl_movement.setText(f"{total} ({remaining})")

        # 5. Status
        self.lbl_status.setText(unit.status.name.title() if hasattr(unit.status, 'name') else str(unit.status))

        # 6. Allegiance: "Allegiance (Land)"
        land = unit.land if unit.land else "other"
        # unit.land is usually country ID or dragonflight name
        self.lbl_allegiance.setText(f"{unit.allegiance.title()} ({land.title()})")

        # 7. Equipment
        if unit.equipment:
            # Assuming equipment list contains objects with 'id' or 'name' or just strings?
            # Loader puts Asset objects. Asset objects have 'spec.id' or similar?
            # Looking at previous context (UnitTable), it accessed `a.spec.id`.
            # Let's try to get a friendly name if possible, otherwise ID.
            names = []
            for item in unit.equipment:
                if hasattr(item, 'spec') and hasattr(item.spec, 'id'):
                    names.append(item.spec.id.replace('_', ' ').title())
                elif hasattr(item, 'id'):
                    names.append(item.id.replace('_', ' ').title())
                else:
                    names.append(str(item))
            self.lbl_equipment.setText(", ".join(names))
        else:
            self.lbl_equipment.setText("None")

        # 8. Terrain Affinity
        # If unit can fly -> "Flying" (e.g. Wing, Citadel)
        # If it's a fleet -> "Ocean"
        # Otherwise -> terrain affinity if present, else "Clear"

        # Check for Flying
        # FlyingCitadel is a class, Wing is a class. Or use unit_type.
        # Check UnitType enum if available on unit.
        is_flying = False
        if unit.unit_type in (UnitType.WING, UnitType.CITADEL):
            is_flying = True

        is_fleet = (unit.unit_type == UnitType.FLEET)

        if is_flying:
            self.lbl_terrain.setText("Flying")
        elif is_fleet:
            self.lbl_terrain.setText("Ocean")
        elif unit.spec.terrain_affinity:
            self.lbl_terrain.setText(unit.spec.terrain_affinity.title())
        else:
            self.lbl_terrain.setText("Clear")

    def set_game_state(self, game_state):
        self.game_state = game_state
        self.mini_map.game_state = game_state
        if self.game_state.map:
            self.mini_map.sync_with_model()

    def _setup_libra_font(self):
        font_id = QFontDatabase.addApplicationFont(LIBRA_FONT)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                font = QFont(families[0], 16)
                self.lbl_unit_name.setFont(font)

    @Slot(str, int, int, str)
    def update_hex_info(self, terrain, col, row, location):
        """Updates the selection label with hover info."""
        text = f"{terrain} ({col}, {row})\n{location}"
        self.selection_label.setText(text)

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
