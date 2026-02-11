import sys
from time import perf_counter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QTableWidget,
                               QHeaderView, QTableWidgetItem, QFrame, QStyleOptionButton, QStyle, QGraphicsScene)
from PySide6.QtCore import Qt, Signal, QSize, QRect, QRectF
from PySide6.QtGui import QColor, QFontDatabase, QFont, QIcon, QPainter, QPixmap

from src.content.config import UNIT_ICON_SIZE, LIBRA_FONT, DEBUG
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
    
    _icon_cache = {}
    _icon_cache_hits = 0
    _icon_cache_misses = 0

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
        self.verticalHeader().setDefaultSectionSize(max(UNIT_ICON_SIZE + 4, 28))
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

    def _get_checkbox_item(self, row):
        if UnitColumn.CHECKBOX not in self.columns_config:
            return None
        return self.item(row, 0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid() and UnitColumn.CHECKBOX in self.columns_config:
                if index.column() != 0:
                    item = self._get_checkbox_item(index.row())
                    if item:
                        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                        item.setCheckState(new_state)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid() and UnitColumn.CHECKBOX in self.columns_config:
                self.blockSignals(True)
                for row in range(self.rowCount()):
                    item = self._get_checkbox_item(row)
                    if item:
                        item.setCheckState(Qt.Checked if row == index.row() else Qt.Unchecked)
                self.blockSignals(False)
                first_item = self._get_checkbox_item(index.row())
                if first_item:
                    self.itemChanged.emit(first_item)
        super().mouseDoubleClickEvent(event)

    def set_units(self, units, game_state=None):
        t0 = perf_counter()
        hits_before, misses_before = self.get_icon_cache_stats()
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
        dt_ms = (perf_counter() - t0) * 1000.0
        hits_after, misses_after = self.get_icon_cache_stats()
        delta_hits = hits_after - hits_before
        delta_misses = misses_after - misses_before
        if DEBUG and (dt_ms >= 40.0 or len(units) >= 60):
            print(
                f"[perf] UnitTable.set_units rows={len(units)} "
                f"time_ms={dt_ms:.1f} icon_hits={delta_hits} icon_misses={delta_misses}"
            )

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

        color_key = color.name(QColor.HexArgb)
        cache_key = (
            UNIT_ICON_SIZE,
            color_key,
            str(getattr(unit, "id", "")),
            int(getattr(unit, "ordinal", 0) or 0),
            str(getattr(getattr(unit, "unit_type", None), "value", getattr(unit, "unit_type", ""))),
            str(getattr(getattr(unit, "race", None), "value", getattr(unit, "race", ""))),
            str(getattr(unit, "allegiance", "")),
            str(getattr(getattr(unit, "status", None), "name", getattr(unit, "status", ""))),
            int(getattr(unit, "movement", 0) or 0),
            int(getattr(unit, "movement_points", getattr(unit, "movement", 0)) or 0),
            bool(getattr(unit, "attacked_this_turn", False)),
            int(getattr(unit, "combat_rating", 0) or 0),
            int(getattr(unit, "tactical_rating", 0) or 0),
        )
        cached = self._icon_cache.get(cache_key)
        if cached is not None:
            self.__class__._icon_cache_hits += 1
            return cached

        self.__class__._icon_cache_misses += 1
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

        if len(self._icon_cache) > 5000:
            self._icon_cache.clear()
        self._icon_cache[cache_key] = pixmap
        return pixmap

    @classmethod
    def get_icon_cache_stats(cls):
        return cls._icon_cache_hits, cls._icon_cache_misses

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
        self._group_order = []
        self._group_widgets = {}  # group_name -> (label_widget, table_widget)
        
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
        t0 = perf_counter()
        if not self.game_state:
            return
        groups_data = self._build_groups_data()
        new_order = [name for name, _units, _style in groups_data]

        if new_order != self._group_order:
            self._rebuild_group_widgets(groups_data)
            phase = "rebuilt"
        else:
            self._update_existing_group_widgets(groups_data)
            phase = "updated"

        dt_ms = (perf_counter() - t0) * 1000.0
        if DEBUG:
            print(
                f"[perf] AllegiancePanel.refresh allegiance={self.allegiance} "
                f"tables={len(self.tables)} mode={phase} time_ms={dt_ms:.1f}"
            )

    def _build_groups_data(self):
        processed_units = set()
        groups_data = []

        countries = [c for c in self.game_state.countries.values() if c.allegiance == self.allegiance]
        countries.sort(key=lambda x: x.id)

        for country in countries:
            units = [u for u in self.game_state.units if u.land == country.id]
            processed_units.update(units)
            groups_data.append((
                country.id.title(),
                units,
                "font-weight: bold; background-color: #EEE; border: 1px solid #CCC;",
            ))

        remaining_units = [u for u in self.game_state.units if u.allegiance == self.allegiance and u not in processed_units]
        if remaining_units:
            grouped = {}
            for unit in remaining_units:
                land_val = str(unit.land).lower() if unit.land else ""
                if land_val in DRAGONFLIGHTS:
                    group_name = f"{land_val.title()} Dragonflight"
                else:
                    group_name = "Others / Independent"
                grouped.setdefault(group_name, []).append(unit)

            for name in sorted(grouped.keys()):
                groups_data.append((
                    name,
                    grouped[name],
                    "font-weight: bold; background-color: #E0E0E0; border: 1px dashed #999;",
                ))
        return groups_data

    def _rebuild_group_widgets(self, groups_data):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tables.clear()
        self._group_widgets.clear()

        for name, units, style in groups_data:
            c_lbl = QLabel(name)
            c_lbl.setStyleSheet(style)
            c_lbl.setAlignment(Qt.AlignCenter)
            self.container_layout.addWidget(c_lbl)

            table = UnitTable(self.columns)
            table.itemSelectionChanged.connect(lambda t=table: self.on_table_selection(t))
            table.set_units(units, self.game_state)
            self._adjust_table_height(table)
            self.container_layout.addWidget(table)
            self.tables.append(table)
            self._group_widgets[name] = (c_lbl, table)

        self._group_order = [name for name, _units, _style in groups_data]

    def _update_existing_group_widgets(self, groups_data):
        self.tables = []
        for name, units, _style in groups_data:
            pair = self._group_widgets.get(name)
            if not pair:
                self._rebuild_group_widgets(groups_data)
                return
            _label, table = pair
            table.set_units(units, self.game_state)
            self._adjust_table_height(table)
            self.tables.append(table)

    def _adjust_table_height(self, table):
        h = table.horizontalHeader().height()
        for r in range(table.rowCount()):
            h += table.rowHeight(r)
        table.setFixedHeight(h + 2)

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
