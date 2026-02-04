import sys
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QTableWidget,
                               QHeaderView, QTableWidgetItem, QFrame, QStyleOptionButton, QStyle, QGraphicsScene)
from PySide6.QtCore import Qt, Signal, QSize, QRect, QRectF
from PySide6.QtGui import QColor, QFontDatabase, QFont, QIcon, QPainter, QPixmap

from src.content.config import UNIT_ICON_SIZE, LIBRA_FONT
from src.content.constants import DRAGONFLIGHTS
from src.content.specs import UnitColumn
from src.gui.map_items import UnitCounter

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

class UnitTable(QTableWidget):
    """
    A reusable table widget for displaying units.
    columns: list of UnitColumn enums.
    """
    
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns_config = columns
        self.current_units = []
        self._init_ui()
        
    def _init_ui(self):
        self.setColumnCount(len(self.columns_config))
        
        # Use Enum values as header labels
        headers = [col.value for col in self.columns_config]
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setIconSize(QSize(UNIT_ICON_SIZE, UNIT_ICON_SIZE))
        
        # Default behavior
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)

        # Checkbox special handling
        if UnitColumn.CHECKBOX in self.columns_config:
            self.header_checkbox = CheckBoxHeader(Qt.Horizontal, self)
            self.setHorizontalHeader(self.header_checkbox)
            self.header_checkbox.toggled.connect(self.toggle_all_rows)
            # Adjust first col
            self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)

        # Adjust other columns
        for i, col in enumerate(self.columns_config):
            if col == UnitColumn.NAME:
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
            elif col != UnitColumn.CHECKBOX:
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)

    def set_units(self, units, game_state=None):
        self.current_units = units
        self.game_state = game_state # Needed for colors/rendering
        self.blockSignals(True)
        self.setRowCount(0)
        
        for row, unit in enumerate(units):
            self.insertRow(row)
            
            for col_idx, col_type in enumerate(self.columns_config):
                item = self._create_item(col_type, unit)
                self.setItem(row, col_idx, item)
                
            # Store unit in user data of the first item
            if self.item(row, 0):
                self.item(row, 0).setData(Qt.UserRole, unit)
                
        self.blockSignals(False)
        self.resizeRowsToContents()

    def _create_item(self, col_type: UnitColumn, unit):
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

        if col_type == UnitColumn.CHECKBOX:
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)

        elif col_type == UnitColumn.ICON:
            pixmap = self._render_unit_icon(unit)
            item.setIcon(QIcon(pixmap))

        elif col_type == UnitColumn.NAME:
            item.setText(str(unit.id))

        elif col_type == UnitColumn.STATUS:
            s_str = unit.status.name.title() if hasattr(unit.status, 'name') else str(unit.status)
            item.setText(s_str)

        elif col_type == UnitColumn.RATING:
            rating_str = f"{unit.combat_rating}"
            if unit.tactical_rating and unit.combat_rating != 0:
                rating_str = f"{unit.combat_rating}/{unit.tactical_rating}"
            elif unit.combat_rating == 0 and unit.tactical_rating:
                rating_str = f"{unit.tactical_rating}"
            item.setText(rating_str)

        elif col_type == UnitColumn.MOVE:
            total = unit.movement
            rem = getattr(unit, 'movement_points', total)
            item.setText(f"{rem} ({total})")

        elif col_type == UnitColumn.POS:
            if unit.is_on_map and unit.position and unit.position != (None, None):
                item.setText(f"{unit.position}")
            else:
                item.setText("-")

        elif col_type == UnitColumn.TYPE:
            item.setText(str(unit.unit_type.value if unit.unit_type else "-"))

        elif col_type == UnitColumn.EQUIPMENT:
            equip_str = "-"
            if hasattr(unit, 'equipment') and unit.equipment:
                equip_str = ", ".join([a.spec.id for a in unit.equipment])
            item.setText(equip_str)

        return item
        
    def _render_unit_icon(self, unit):
        color = QColor("gray")
        # Need access to game_state for country colors
        if hasattr(self, 'game_state') and self.game_state and unit.land in self.game_state.countries:
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

    def toggle_all_rows(self, checked):
        self.blockSignals(True)
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.blockSignals(False)
        # Emit signal to notify caller to re-scan selection if needed
        self.itemChanged.emit(self.item(0, 0)) # Hack to trigger notify

class AllegiancePanel(QWidget):
    """
    A panel that displays units for a specific allegiance, grouped by country.
    Used in StatusTab and AssetsTab.
    """
    unit_selected = Signal(object) # Emits the selected unit (or None)

    def __init__(self, game_state, allegiance, columns, parent=None, title=None):
        super().__init__(parent)
        self.game_state = game_state
        self.allegiance = allegiance
        self.columns = columns
        self.tables = [] # Keep track of created tables
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0,0,0,0)

        if title:
            lbl = QLabel(title)
            lbl.setAlignment(Qt.AlignCenter)
            
            font_db = QFontDatabase()
            font_id = font_db.addApplicationFont(LIBRA_FONT)
            if font_id != -1:
                families = font_db.applicationFontFamilies(font_id)
                if families:
                    font = QFont(families[0], 18)
                    lbl.setFont(font)
            else:
                f = lbl.font()
                f.setPointSize(18)
                lbl.setFont(f)
            
            self.main_layout.addWidget(lbl)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.main_layout.addWidget(self.scroll)
        
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        
        self.refresh()

    def refresh(self):
        # Clear existing
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tables.clear()
        
        if not self.game_state:
            return

        processed_units = set()

        # Filter countries
        countries = [c for c in self.game_state.countries.values() if c.allegiance == self.allegiance]
        countries.sort(key=lambda x: x.id)
        
        for country in countries:
             # Get units
            units = [u for u in self.game_state.units if u.land == country.id]
            processed_units.update(units)

            # Show empty countries logic same as original StatusTab
            
            # Header
            c_lbl = QLabel(country.id.title())
            c_lbl.setStyleSheet("font-weight: bold; background-color: #EEE; border: 1px solid #CCC;")
            c_lbl.setAlignment(Qt.AlignCenter)
            self.container_layout.addWidget(c_lbl)
            
            # Table
            table = UnitTable(self.columns)
            # Connect selection
            table.itemSelectionChanged.connect(lambda t=table: self.on_table_selection(t))
            
            table.set_units(units, self.game_state)
            
            # Adjust height
            h = table.horizontalHeader().height()
            for r in range(table.rowCount()):
                h += table.rowHeight(r)
            table.setFixedHeight(h + 2)
            
            self.container_layout.addWidget(table)
            self.tables.append(table)

        # --- Handle Stateless / Independent Units ---
        remaining_units = [u for u in self.game_state.units
                           if u.allegiance == self.allegiance and u not in processed_units]

        if remaining_units:
            groups = {}
            for unit in remaining_units:
                # Determine Group
                land_val = str(unit.land).lower() if unit.land else ""
                if land_val in DRAGONFLIGHTS:
                    group_name = f"{land_val.title()} Dragonflight"
                else:
                    group_name = "Others / Independent"

                if group_name not in groups:
                    groups[group_name] = []
                groups[group_name].append(unit)

            # Create Tables for groups
            for name in sorted(groups.keys()):
                units = groups[name]

                # Header
                c_lbl = QLabel(name)
                c_lbl.setStyleSheet("font-weight: bold; background-color: #E0E0E0; border: 1px dashed #999;")
                c_lbl.setAlignment(Qt.AlignCenter)
                self.container_layout.addWidget(c_lbl)

                # Table
                table = UnitTable(self.columns)
                table.itemSelectionChanged.connect(lambda t=table: self.on_table_selection(t))
                table.set_units(units, self.game_state)

                # Adjust height
                h = table.horizontalHeader().height()
                for r in range(table.rowCount()):
                    h += table.rowHeight(r)
                table.setFixedHeight(h + 2)

                self.container_layout.addWidget(table)
                self.tables.append(table)

    def on_table_selection(self, sender_table):
        # Enforce exclusive selection across tables
        selected_items = sender_table.selectedItems()
        if not selected_items:
            return

        # Block signals to prevent recursion
        for table in self.tables:
            if table != sender_table:
                table.blockSignals(True)
                table.clearSelection()
                table.blockSignals(False)
        
        # Emit the selected unit
        row = selected_items[0].row()
        unit_item = sender_table.item(row, 0)
        if unit_item:
            unit = unit_item.data(Qt.UserRole)
            self.unit_selected.emit(unit)
