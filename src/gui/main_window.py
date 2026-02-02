import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QFrame, QLabel, QGridLayout, QPushButton, QTextEdit,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QStyleOptionButton, QStyle, QGraphicsScene, QTabWidget,
                               QScrollArea, QTreeWidget, QTreeWidgetItem, QLineEdit, QSplitter)
from PySide6.QtCore import Qt, Signal, Slot, QRect, QRectF, QObject, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon, QAction, QFontDatabase, QFont

from src.content.config import APP_NAME, UNIT_ICON_SIZE
from src.content.constants import WS, HL, NEUTRAL
from src.gui.map_view import AnsalonMapView
from src.gui.map_items import UnitCounter
from src.content.specs import AssetType

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

class CheckBoxHeader(QHeaderView):
    """A custom header with a checkbox in the first column."""
    toggled = Signal(bool)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.isChecked = False

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()

        if logicalIndex == 0:
            option = QStyleOptionButton()
            # Center the checkbox
            checkbox_width = 20
            checkbox_height = 20
            x = rect.left() + (rect.width() - checkbox_width) // 2
            y = rect.top() + (rect.height() - checkbox_height) // 2

            option.rect = QRect(x, y, checkbox_width, checkbox_height)
            option.state = QStyle.State_Enabled | QStyle.State_Active
            if self.isChecked:
                option.state |= QStyle.State_On
            else:
                option.state |= QStyle.State_Off
            self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, option, painter)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            logicalIndex = self.logicalIndexAt(event.pos())
            if logicalIndex == 0:
                self.isChecked = not self.isChecked
                self.toggled.emit(self.isChecked)
                self.viewport().update()
            else:
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

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

        # Unit Info placeholder (Previously static unit box, replacing with Table)
        layout.addWidget(QLabel("Selected Units Stack:"))

        self.units_table = QTableWidget()
        self.units_table.setColumnCount(5)

        # Setup Custom Header for Select All
        self.header_checkbox = CheckBoxHeader(Qt.Horizontal, self.units_table)
        self.units_table.setHorizontalHeader(self.header_checkbox)
        self.header_checkbox.toggled.connect(self.toggle_all_rows)

        self.units_table.setHorizontalHeaderLabels(["", "Icon", "Name", "Rating", "Mov"])
        self.units_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Checkbox
        self.units_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Icon
        self.units_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)  # ID
        self.units_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.units_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.units_table.verticalHeader().setVisible(False)
        self.units_table.setSelectionBehavior(QTableWidget.SelectRows)

        # Double the icon size for the table display
        self.units_table.setIconSize(QSize(UNIT_ICON_SIZE, UNIT_ICON_SIZE))

        layout.addWidget(self.units_table)

        layout.addStretch()

        self.units_table.itemChanged.connect(self.on_item_changed)
        self.current_units = []

    def set_game_state(self, game_state):
        self.game_state = game_state

    @Slot(bool)
    def toggle_all_rows(self, checked):
        self.units_table.blockSignals(True)
        for row in range(self.units_table.rowCount()):
            item = self.units_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.units_table.blockSignals(False)
        self.notify_selection()

    @Slot(list)
    def update_unit_table(self, units):
        """Populates the table with the provided list of units."""
        self.current_units = units
        self.units_table.blockSignals(True)
        self.units_table.setRowCount(0)

        # Check for Movement Phase to auto-select
        from src.content.specs import GamePhase
        is_movement_phase = self.game_state and self.game_state.phase == GamePhase.MOVEMENT
        is_combat_phase = self.game_state and self.game_state.phase == GamePhase.COMBAT

        # Reset header checkbox
        self.header_checkbox.isChecked = is_movement_phase or is_combat_phase
        self.header_checkbox.viewport().update()

        # Populates table rows with unit properties and selection checkboxes
        for row, unit in enumerate(units):
            self.units_table.insertRow(row)

            # 1. Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if is_movement_phase or is_combat_phase else Qt.Unchecked)
            self.units_table.setItem(row, 0, chk_item)

            # 2. Icon
            icon_pixmap = self._render_unit_icon(unit)
            icon_item = QTableWidgetItem()
            icon_item.setIcon(QIcon(icon_pixmap))
            # Center icon? QTableWidgetItem doesn't center icon easily, typically handled by delegate or simple alignment
            self.units_table.setItem(row, 1, icon_item)

            # 3. ID
            self.units_table.setItem(row, 2, QTableWidgetItem(str(unit.id)))

            # 4. Rating (Combat/Tactical)
            rating = unit.combat_rating if unit.combat_rating != 0 else unit.tactical_rating
            rating_str = f"{rating}"
            if unit.tactical_rating and unit.combat_rating:
                rating_str = f"{unit.combat_rating}/{unit.tactical_rating}" # Show both if applicable

            self.units_table.setItem(row, 3, QTableWidgetItem(rating_str))

            # 5. Movement
            total_mov = unit.movement
            remaining_mov = getattr(unit, 'movement_points', total_mov)
            mov_str = f"{remaining_mov} ({total_mov})"
            self.units_table.setItem(row, 4, QTableWidgetItem(mov_str))

        # Adjust row heights to fit icons
        self.units_table.resizeRowsToContents()
        self.units_table.blockSignals(False)
        #self.units_table.resizeColumnsToContents()

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

    def _render_unit_icon(self, unit):
        """Helper to render a UnitCounter to a QPixmap."""
        # Determine color
        color = QColor("gray")
        if self.game_state and unit.land in self.game_state.countries:
            color = QColor(self.game_state.countries[unit.land].color)

        scene = QGraphicsScene()
        counter = UnitCounter(unit, color)
        scene.addItem(counter)

        pixmap = QPixmap(UNIT_ICON_SIZE, UNIT_ICON_SIZE)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # UnitCounter is typically centered at 0,0 with size ~ UNIT_SIZE (e.g. 50 or 60)
        # We map the scene rect to the pixmap
        target_rect = QRectF(0, 0, UNIT_ICON_SIZE, UNIT_ICON_SIZE)
        source_rect = counter.boundingRect()

        scene.render(painter, target_rect, source_rect)
        painter.end()
        return pixmap

class AssetDetails(QFrame):
    """Lower section of the Assets Tab showing details."""
    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.init_ui()
        self.current_asset = None
        self.current_unit = None

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Top: Picture + Info
        top_row = QHBoxLayout()

        # Picture
        self.pic_label = QLabel()
        self.pic_label.setFixedSize(150, 150)
        self.pic_label.setAlignment(Qt.AlignCenter)
        self.pic_label.setStyleSheet("border: 2px dashed gray;")
        top_row.addWidget(self.pic_label)

        # Info (Name + Bonus)
        info_col = QVBoxLayout()

        self.name_label = QLabel("Select an asset")
        # Set Font to Libra
        font_db = QFontDatabase()
        font_id = font_db.addApplicationFont("assets/font/Libra Regular.otf")
        if font_id != -1:
            families = font_db.applicationFontFamilies(font_id)
            if families:
                self.name_label.setFont(QFont(families[0], 24))

        info_col.addWidget(self.name_label)

        self.bonus_field = QLineEdit()
        self.bonus_field.setReadOnly(True)
        self.bonus_field.setPlaceholderText("Asset Bonus")
        info_col.addWidget(self.bonus_field)

        top_row.addLayout(info_col)
        layout.addLayout(top_row)

        # Description
        self.desc_field = QTextEdit()
        self.desc_field.setReadOnly(True)
        self.desc_field.setMaximumHeight(80)
        layout.addWidget(self.desc_field)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_assign = QPushButton("Assign")
        self.btn_remove = QPushButton("Remove")
        self.btn_assign.setEnabled(False)
        self.btn_remove.setEnabled(False)

        btn_layout.addWidget(self.btn_assign)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def display_asset(self, asset):
        self.current_asset = asset

        if not asset:
            self.name_label.setText("Select an asset")
            self.pic_label.clear()
            self.pic_label.setStyleSheet("border: 2px dashed gray;")
            self.bonus_field.clear()
            self.desc_field.clear()
            return

        self.name_label.setText(asset.spec.id.replace("_", " ").title())
        self.desc_field.setText(asset.description)

        # Bonus Text
        if isinstance(asset.bonus, dict):
            bonus_str = ", ".join([f"{k}: {v}" for k,v in asset.bonus.items()])
        else:
            bonus_str = str(asset.bonus)
        self.bonus_field.setText(bonus_str)

        # Picture Border Color
        border_color = "black" # Default Artifact
        if asset.asset_type == AssetType.RESOURCE:
            border_color = "silver"
        elif asset.asset_type == AssetType.BANNER:
            border_color = "green"

        self.pic_label.setStyleSheet(f"border: 4px solid {border_color};")

        # Load Picture
        pix = QPixmap(f"assets/img/{asset.spec.picture}")
        if not pix.isNull():
            self.pic_label.setPixmap(pix.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.pic_label.setText("No Image")

    def update_buttons_state(self, unit):
        """Logic to enable/disable buttons based on selection."""
        self.current_unit = unit
        asset = self.current_asset

        # Reset
        self.btn_assign.setEnabled(False)
        self.btn_remove.setEnabled(False)

        if not asset:
            return

        # Case: Asset is not equippable
        if not asset.is_equippable:
            return

        # Case: Unit with artifact is selected (Removal logic)
        if unit and hasattr(unit, 'equipment') and unit.equipment:
            # If the displayed asset IS the one on the unit, enable remove
            if asset in unit.equipment:
                self.btn_remove.setEnabled(True)
            return

        # Case: Asset selected, Empty Unit selected (Assign logic)
        if unit and (not hasattr(unit, 'equipment') or not unit.equipment):
            # Only if asset is currently free (not assigned to someone else)
            if asset.assigned_to is None:
                self.btn_assign.setEnabled(True)

class AssetsTab(QWidget):
    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Upper Section (Split 2/3 and 1/3) ---
        upper_widget = QWidget()
        upper_layout = QHBoxLayout(upper_widget)

        # 1. Unit Table (Left - 2/3)
        self.unit_table = QTableWidget()
        self.unit_table.setColumnCount(4)
        self.unit_table.setHorizontalHeaderLabels(["Icon", "Name", "Type", "Equipment"])
        self.unit_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.unit_table.verticalHeader().setVisible(False)
        self.unit_table.setIconSize(QSize(UNIT_ICON_SIZE, UNIT_ICON_SIZE))
        self.unit_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.unit_table.setSelectionMode(QTableWidget.SingleSelection)

        upper_layout.addWidget(self.unit_table, stretch=2)

        # 2. Asset Tree (Right - 1/3)
        self.asset_tree = QTreeWidget()
        self.asset_tree.setHeaderLabel("Player Assets")
        upper_layout.addWidget(self.asset_tree, stretch=1)

        main_layout.addWidget(upper_widget, stretch=1)

        # --- Lower Section ---
        self.details_panel = AssetDetails()
        self.details_panel.btn_assign.clicked.connect(self.on_assign_clicked)
        self.details_panel.btn_remove.clicked.connect(self.on_remove_clicked)
        main_layout.addWidget(self.details_panel, stretch=0)

        # Signals
        self.unit_table.itemSelectionChanged.connect(self.on_unit_selected)
        self.asset_tree.itemSelectionChanged.connect(self.on_tree_asset_selected)

    def refresh(self):
        """Reloads data from GameState."""
        if not self.game_state or not self.game_state.current_player:
            return

        player = self.game_state.current_player

        # 1. Refresh Unit Table
        self.unit_table.blockSignals(True)
        self.unit_table.setRowCount(0)

        # Filter units for current player
        units = [u for u in self.game_state.units if u.allegiance == player.allegiance]
        self.current_units_map = {} # Row -> Unit

        for row, unit in enumerate(units):
            self.unit_table.insertRow(row)
            self.current_units_map[row] = unit

            # Icon
            # (Assuming reuse of _render_unit_icon logic or placeholder)
            icon_item = QTableWidgetItem(str(unit.id)[:2]) # Placeholder if icon renderer not avail in this scope
            self.unit_table.setItem(row, 0, icon_item)

            # Name
            self.unit_table.setItem(row, 1, QTableWidgetItem(str(unit.id)))

            # Type
            self.unit_table.setItem(row, 2, QTableWidgetItem(str(unit.unit_type)))

            # Equipment
            equip_str = "-"
            if hasattr(unit, 'equipment') and unit.equipment:
                equip_str = ", ".join([a.spec.id for a in unit.equipment])
            self.unit_table.setItem(row, 3, QTableWidgetItem(equip_str))

        self.unit_table.blockSignals(False)

        # 2. Refresh Asset Tree
        self.asset_tree.blockSignals(True)
        self.asset_tree.clear()

        cats = {
            AssetType.ARTIFACT: QTreeWidgetItem(["Artifacts"]),
            AssetType.RESOURCE: QTreeWidgetItem(["Resources"]),
            AssetType.BANNER: QTreeWidgetItem(["Banners"])
        }
        for c in cats.values():
            self.asset_tree.addTopLevelItem(c)

        for asset_id, asset in player.assets.items():
            node = QTreeWidgetItem([asset.spec.id.replace("_", " ").title()])
            node.setData(0, Qt.UserRole, asset) # Store asset object

            # Add to category
            if asset.asset_type in cats:
                cats[asset.asset_type].addChild(node)
            else:
                cats[AssetType.ARTIFACT].addChild(node) # Fallback

        self.asset_tree.expandAll()
        self.asset_tree.blockSignals(False)

    def on_unit_selected(self):
        selected_items = self.unit_table.selectedItems()
        if not selected_items:
            self.details_panel.update_buttons_state(None)
            return

        row = selected_items[0].row()
        unit = self.current_units_map.get(row)

        # Logic: If unit has artifact, select it in details
        asset_to_show = None
        if hasattr(unit, 'equipment') and unit.equipment:
            asset_to_show = unit.equipment[0] # Show first

            # Deselect tree to avoid confusion?
            # Prompt says: "If the unit has an artifact equipped, the asset in the tree view will be deselected automatically."
            self.asset_tree.blockSignals(True)
            self.asset_tree.clearSelection()
            self.asset_tree.blockSignals(False)

        # If unit has NO artifact, we keep the tree selection if exists
        elif self.asset_tree.selectedItems():
            item = self.asset_tree.selectedItems()[0]
            asset_to_show = item.data(0, Qt.UserRole)

        self.details_panel.display_asset(asset_to_show)
        self.details_panel.update_buttons_state(unit)

    def on_tree_asset_selected(self):
        selected = self.asset_tree.selectedItems()
        if not selected:
            return

        item = selected[0]
        asset = item.data(0, Qt.UserRole)
        if not asset: return # Category label

        # Check currently selected unit
        unit = None
        sel_rows = self.unit_table.selectedIndexes()
        if sel_rows:
            unit = self.current_units_map.get(sel_rows[0].row())

        self.details_panel.display_asset(asset)
        self.details_panel.update_buttons_state(unit)

    def on_assign_clicked(self):
        unit = self.details_panel.current_unit
        asset = self.details_panel.current_asset
        if unit and asset:
            asset.apply_to(unit)
            self.refresh() # Update table
            # Reselect
            self.details_panel.display_asset(asset)
            self.details_panel.update_buttons_state(unit)

    def on_remove_clicked(self):
        unit = self.details_panel.current_unit
        asset = self.details_panel.current_asset
        if unit and asset:
            asset.remove_from(unit)
            self.refresh()
            self.details_panel.display_asset(asset)
            self.details_panel.update_buttons_state(unit)

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

        # Create 3 panels
        self.main_layout.addWidget(self.create_panel("Whitestone", WS))
        self.main_layout.addWidget(self.create_panel("Highlord", HL))
        self.main_layout.addWidget(self.create_panel("Neutral", NEUTRAL))

    def create_panel(self, title, alliance):
        panel = QWidget()
        v_layout = QVBoxLayout(panel)
        v_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Label
        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignCenter)

        font_db = QFontDatabase()
        font_id = font_db.addApplicationFont("assets/font/Libra Regular.otf")
        if font_id != -1:
            families = font_db.applicationFontFamilies(font_id)
            if families:
                font = QFont(families[0], 18)
                lbl.setFont(font)
        else:
            f = lbl.font()
            f.setPointSize(18)
            lbl.setFont(f)

        v_layout.addWidget(lbl)

        # 2. Scroll Area containing list of Country Tables
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setAlignment(Qt.AlignTop)

        # Filter countries
        countries = [c for c in self.game_state.countries.values() if c.allegiance == alliance]
        countries.sort(key=lambda x: x.id)

        for country in countries:
            # Country Header
            c_lbl = QLabel(country.id.title())
            c_lbl.setStyleSheet("font-weight: bold; background-color: #EEE; border: 1px solid #CCC;")
            c_lbl.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(c_lbl)

            # Table
            table = QTableWidget()
            table.setColumnCount(6)
            table.setHorizontalHeaderLabels(["Icon", "Name", "Status", "Rating", "Move", "Pos"])
            table.verticalHeader().setVisible(False)

            # Column sizing
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Icon
            header.setSectionResizeMode(1, QHeaderView.Stretch)  # Name
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Rating
            header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Move
            header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Pos

            # Get units
            units = [u for u in self.game_state.units if u.land == country.id]
            table.setRowCount(len(units))
            table.setIconSize(QSize(UNIT_ICON_SIZE, UNIT_ICON_SIZE))

            for row, unit in enumerate(units):
                # Icon
                icon_pixmap = self._render_unit_icon(unit)
                table.setItem(row, 0, QTableWidgetItem(QIcon(icon_pixmap), ""))

                # Name
                table.setItem(row, 1, QTableWidgetItem(str(unit.id)))

                # Status
                s_str = unit.status.name.title() if hasattr(unit.status, 'name') else str(unit.status)
                table.setItem(row, 2, QTableWidgetItem(s_str))

                # Rating
                rating_str = f"{unit.combat_rating}"
                if unit.tactical_rating and unit.combat_rating != 0:
                    rating_str = f"{unit.combat_rating}/{unit.tactical_rating}"
                elif unit.combat_rating == 0 and unit.tactical_rating:
                    rating_str = f"{unit.tactical_rating}"
                table.setItem(row, 3, QTableWidgetItem(rating_str))

                # Move
                total = unit.movement
                rem = getattr(unit, 'movement_points', total)
                table.setItem(row, 4, QTableWidgetItem(f"{rem} ({total})"))

                # Pos
                if unit.is_on_map and unit.position and unit.position != (None, None):
                    table.setItem(row, 5, QTableWidgetItem(f"{unit.position}"))
                else:
                    table.setItem(row, 5, QTableWidgetItem("-"))

            table.resizeRowsToContents()
            # Set height
            h = table.horizontalHeader().height()
            for r in range(table.rowCount()):
                h += table.rowHeight(r)
            table.setFixedHeight(h + 2)  # small buffer

            container_layout.addWidget(table)

        scroll.setWidget(container)
        v_layout.addWidget(scroll)

        return panel

    def _render_unit_icon(self, unit):
        color = QColor("gray")
        if self.game_state and unit.land in self.game_state.countries:
            color = QColor(self.game_state.countries[unit.land].color)

        scene = QGraphicsScene()
        counter = UnitCounter(unit, color)
        scene.addItem(counter)

        pixmap = QPixmap(UNIT_ICON_SIZE, UNIT_ICON_SIZE)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        target_rect = QRectF(0, 0, UNIT_ICON_SIZE, UNIT_ICON_SIZE)
        source_rect = counter.boundingRect()

        scene.render(painter, target_rect, source_rect)
        painter.end()
        return pixmap


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
        self.heroes_tab = QLabel("Heroes Registry")
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

