from collections import defaultdict
from types import SimpleNamespace
from time import perf_counter
from typing import Optional, Dict, Any, Callable
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QTableWidget,
                               QHeaderView, QTableWidgetItem, QFrame, QStyleOptionButton, QStyle, QGraphicsScene)
from PySide6.QtCore import Qt, Signal, QSize, QRect, QRectF
from PySide6.QtGui import QColor, QFontDatabase, QFont, QIcon, QPainter, QPixmap

from src.content.translator import Translator
from src.content.tools import debug_print
from src.content.config import UNIT_ICON_SIZE, LIBRA_FONT, DEBUG
from src.content.constants import DRAGONFLIGHTS
from src.content.specs import UnitColumn
from src.content.tools import TextFormatter
from src.gui.map_items import UnitCounter

translator = Translator()

class CheckBoxHeader(QHeaderView):
    """A custom header with a checkbox in the first column."""
    toggled = Signal(bool)

    def __init__(self, orientation, parent=None):
        """Initialize the checkbox header with the given orientation.
        
        Args:
            orientation: Qt.Orientation (Horizontal/Vertical) for the header.
            parent: Optional parent widget.
        """
        super().__init__(orientation, parent)
        self.isChecked = False

    def paintSection(self, painter, rect, logicalIndex):
        """Paint a header section, drawing a checkbox in the first column.
        
        Args:
            painter: QPainter instance to draw with.
            rect: QRect defining the section's area.
            logicalIndex: Logical index of the section being painted.
        """
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
        """Handle mouse press events to toggle the header checkbox.
        
        Toggles the checkbox when the first column's header is clicked.
        
        Args:
            event: QMouseEvent instance.
        """
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
        """Initialize the unit table with specified columns.
        
        Args:
            columns: List of UnitColumn enums defining the table's columns.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.columns_config = columns
        self.current_units = []
        self._init_ui()
        
    def _init_ui(self):
        """Set up the table's UI elements, columns, and header configuration."""
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
        """Retrieve the checkbox item for the given row, if applicable.
        
        Args:
            row: Row index to fetch the checkbox item from.
            
        Returns:
            QTableWidgetItem for the checkbox, or None if not applicable.
        """
        if UnitColumn.CHECKBOX not in self.columns_config:
            return None
        return self.item(row, 0)

    def mousePressEvent(self, event):
        """Handle mouse press events to toggle checkboxes in non-first columns.
        
        Args:
            event: QMouseEvent instance.
        """
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid() and UnitColumn.CHECKBOX in self.columns_config:
                if index.column() != 0:
                    item = self._get_checkbox_item(index.row())
                    if item and (item.flags() & Qt.ItemIsEnabled):
                        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                        item.setCheckState(new_state)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click events to select a single row's checkbox.
        
        Checks only the double-clicked row, unchecking all others.
        
        Args:
            event: QMouseEvent instance.
        """
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid() and UnitColumn.CHECKBOX in self.columns_config:
                self.blockSignals(True)
                for row in range(self.rowCount()):
                    item = self._get_checkbox_item(row)
                    if item and (item.flags() & Qt.ItemIsEnabled):
                        item.setCheckState(Qt.Checked if row == index.row() else Qt.Unchecked)
                self.blockSignals(False)
                first_item = self._get_checkbox_item(index.row())
                if first_item and (first_item.flags() & Qt.ItemIsEnabled):
                    self.itemChanged.emit(first_item)
        super().mouseDoubleClickEvent(event)

    def set_units(self, units, game_state=None):
        """Populate the table with the given list of units.
        
        Clears existing rows and creates new entries for each unit.
        
        Args:
            units: List of unit objects to display.
            game_state: Optional game state for rendering context (e.g., country colors).
        """
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
        """Create a table item for the given column type and unit.
        
        Args:
            col_type: UnitColumn enum specifying the column type.
            unit: Unit object to populate the item with.
            
        Returns:
            QTableWidgetItem configured for the column.
        """
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

        if col_type == UnitColumn.CHECKBOX:
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)

        elif col_type == UnitColumn.ICON:
            pixmap = self._render_unit_icon(unit)
            item.setIcon(QIcon(pixmap))

        elif col_type == UnitColumn.NAME:
            item.setText(TextFormatter.format_unit_log_string(unit))

        elif col_type == UnitColumn.STATUS:
            s_str = unit.status.name.title()
            item.setText(s_str)

        elif col_type == UnitColumn.RATING:
            rating_str = f"{unit.combat_rating}" if unit.combat_rating != 0 else str(unit.tactical_rating)
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
        """Render a unit icon as a QPixmap, using a cache for performance.
        
        Args:
            unit: Unit object to render the icon for.
            
        Returns:
            QPixmap of the rendered unit icon.
        """
        color = QColor("gray")
        # Need access to game_state for country colors
        if hasattr(self, 'game_state') and self.game_state and unit.land in self.game_state.countries:
            color = QColor(self.game_state.countries[unit.land].color)

        color_key = color.name(QColor.HexArgb)
        cache_key = (
            UNIT_ICON_SIZE,
            color_key,
            str(unit.id),
            int(unit.ordinal),
            str(unit.unit_type.value),
            str(unit.race.value),
            str(unit.allegiance),
            str(unit.status.name),
            int(unit.movement),
            int(unit.movement_points),
            bool(unit.attacked_this_turn),
            int(unit.combat_rating),
            int(unit.tactical_rating),
            bool(unit.is_transported),
            (
                str(getattr(getattr(unit, "transport_host", None), "id", "")),
                int(getattr(getattr(unit, "transport_host", None), "ordinal", 0) or 0),
            ),
            int(
                len(getattr(unit, "passengers", []) or [])
                if hasattr(unit, "passengers")
                else 0
            ),
        )
        cached = self._icon_cache.get(cache_key)
        if cached is not None:
            self.__class__._icon_cache_hits += 1
            return cached

        self.__class__._icon_cache_misses += 1
        # Render base counter using a proxy that suppresses transport badges.
        # Then paint badges directly onto the pixmap to avoid Qt scene instability
        # with transport-host object references during rapid UI refresh.
        icon_unit = SimpleNamespace(
            id=unit.id,
            ordinal=unit.ordinal,
            unit_type=unit.unit_type,
            race=unit.race,
            land=unit.land,
            allegiance=unit.allegiance,
            status=unit.status,
            movement=unit.movement,
            movement_points=unit.movement_points,
            attacked_this_turn=unit.attacked_this_turn,
            combat_rating=unit.combat_rating,
            tactical_rating=unit.tactical_rating,
            passengers=[],
            is_transported=False,
            transport_host=None,
        )

        scene = QGraphicsScene()
        counter = UnitCounter(icon_unit, color)
        scene.addItem(counter)

        pixmap = QPixmap(UNIT_ICON_SIZE, UNIT_ICON_SIZE)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        target_rect = QRectF(0, 0, UNIT_ICON_SIZE, UNIT_ICON_SIZE)
        source_rect = counter.boundingRect()

        scene.render(painter, target_rect, source_rect)
        self._draw_transport_overlays(painter, unit, UNIT_ICON_SIZE)
        painter.end()

        if len(self._icon_cache) > 5000:
            self._icon_cache.clear()
        self._icon_cache[cache_key] = pixmap
        return pixmap

    def _draw_transport_overlays(self, painter, unit, size):
        """Draw transport-related overlays (passenger count, host marker) on the icon.
        
        Args:
            painter: QPainter to draw with.
            unit: Unit object to check for transport status.
            size: Size of the icon pixmap.
        """
        # Carrier passenger-count badge
        passengers = getattr(unit, "passengers", None) or []
        if len(passengers) > 0:
            badge_text = str(len(passengers))
            br = max(5, size // 7)
            bx = size - (br * 2) - 2
            by = (size // 2) - br
            badge_rect = QRectF(bx, by, br * 2, br * 2)
            painter.setBrush(QColor(255, 215, 0))
            painter.setPen(QColor(0, 0, 0))
            painter.drawEllipse(badge_rect)
            f = painter.font()
            f.setPointSize(max(6, size // 8))
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # Transported marker badge (host ordinal)
        if bool(unit.is_transported):
            host = unit.transport_host
            if host is not None:
                host_num = host.ordinal
                if host_num is None:
                    host_num = getattr(host, "ordinal_index", None)
                if host_num is not None:
                    host_text = str(host_num)
                    tw = max(12, size // 2 - 2)
                    th = max(10, size // 3 - 1)
                    tx = size - tw - 2
                    ty = 2
                    rect = QRectF(tx, ty, tw, th)
                    painter.setBrush(QColor(200, 200, 200))
                    painter.setPen(QColor(0, 0, 0))
                    painter.drawRoundedRect(rect, 3, 3)
                    f = painter.font()
                    f.setPointSize(max(6, size // 8))
                    f.setBold(True)
                    painter.setFont(f)
                    painter.drawText(rect, Qt.AlignCenter, host_text)

    @classmethod
    def get_icon_cache_stats(cls):
        """Return icon cache hit/miss statistics.
        
        Returns:
            Tuple of (cache_hits, cache_misses).
        """
        return cls._icon_cache_hits, cls._icon_cache_misses

    def toggle_all_rows(self, checked):
        """Toggle all enabled checkbox rows to the given checked state.
        
        Args:
            checked: Boolean indicating whether to check or uncheck all rows.
        """
        self.blockSignals(True)
        first_enabled_item = None
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and (item.flags() & Qt.ItemIsEnabled):
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                if first_enabled_item is None:
                    first_enabled_item = item
        self.blockSignals(False)
        # Emit signal to notify caller to re-scan selection if needed
        if first_enabled_item:
            self.itemChanged.emit(first_enabled_item) # Hack to trigger notify

class AllegiancePanel(QWidget):
    """
    A panel that displays units for a specific allegiance, grouped by country.
    Used in StatusTab and AssetsTab.
    """
    unit_selected = Signal(object) # Emits the selected unit (or None)
    unit_double_clicked = Signal(object) # Emits the double-clicked unit

    def __init__(self, game_state, allegiance, columns, parent=None, title=None, unit_filter: Optional[Callable] = None):
        """Initialize the allegiance panel with game state, allegiance, and columns.
        
        Args:
            game_state: Core game state object.
            allegiance: Allegiance (e.g., HL, WS) to display units for.
            columns: List of UnitColumn enums for the unit tables.
            parent: Optional parent widget.
            title: Optional title for the panel; defaults to allegiance.
            unit_filter: Optional predicate used to exclude units from this panel.
        """
        super().__init__(parent)
        self.game_state = game_state
        self.allegiance = allegiance
        self.columns = columns
        self.unit_filter = unit_filter
        self.base_title = title or str(allegiance)
        self.title_label = None
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
            self.title_label = lbl
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.main_layout.addWidget(self.scroll)
        
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        
        self.refresh()

    def set_title_text(self, text: str):
        """Set the panel's title text, falling back to the base title if empty.
        
        Args:
            text: New title text; uses base_title if None/empty.
        """
        if self.title_label is not None:
            self.title_label.setText(str(text or self.base_title))

    def refresh(self, preindexed: Optional[Dict[str, Any]] = None):
        """Refresh the panel's unit groups, rebuilding or updating widgets as needed.
        
        Args:
            preindexed: Optional precomputed indexes to speed up group building.
        """
        t0 = perf_counter()
        if not self.game_state:
            return
        groups_data = self._build_groups_data(preindexed=preindexed)
        new_order = [name for name, _units, _style in groups_data]

        if new_order != self._group_order:
            self._rebuild_group_widgets(groups_data)
            phase = "rebuilt"
        else:
            self._update_existing_group_widgets(groups_data)
            phase = "updated"

        dt_ms = (perf_counter() - t0) * 1000.0
        debug_print(
                f"[perf] AllegiancePanel.refresh allegiance={self.allegiance} "
                f"tables={len(self.tables)} mode={phase} time_ms={dt_ms:.1f}"
        )

    def _build_groups_data(self, preindexed: Optional[Dict[str, Any]] = None):
        """Build grouped unit data, organized by country and dragonflights.
        
        Args:
            preindexed: Optional precomputed indexes (units_by_land, units_by_allegiance).
            
        Returns:
            List of tuples (group_name, units, style) for each group.
        """
        processed_units = set()
        groups_data = []

        countries = [c for c in self.game_state.countries.values() if c.allegiance == self.allegiance]
        countries.sort(key=lambda x: x.id)

        units_by_land = (preindexed or {}).get("units_by_land") if preindexed else None
        if units_by_land is None:
            units_by_land = defaultdict(list)
            for u in self.game_state.units:
                if self.unit_filter and not self.unit_filter(u):
                    continue
                units_by_land[getattr(u, "land", None)].append(u)
        elif self.unit_filter:
            filtered_units_by_land = defaultdict(list)
            for land, units in units_by_land.items():
                filtered_units_by_land[land].extend(u for u in units if self.unit_filter(u))
            units_by_land = filtered_units_by_land

        allegiance_units = (preindexed or {}).get("units_by_allegiance", {}).get(self.allegiance) if preindexed else None
        if allegiance_units is None:
            allegiance_units = [u for u in self.game_state.units if u.allegiance == self.allegiance]
        if self.unit_filter:
            allegiance_units = [u for u in allegiance_units if self.unit_filter(u)]

        for country in countries:
            units = list(units_by_land.get(country.id, []))
            processed_units.update(units)
            groups_data.append((
                translator.get_country_name(country.id),
                units,
                "font-weight: bold; background-color: rgba(128, 128, 128, 0.15); border: 1px solid #888;",
            ))

        remaining_units = [u for u in allegiance_units if u not in processed_units]
        if remaining_units:
            grouped = {}
            for unit in remaining_units:
                df = getattr(getattr(unit, "spec", None), "dragonflight", None)
                if df and df.lower() in DRAGONFLIGHTS:
                    group_name = translator.get_country_name(df.lower())
                else:
                    group_name = "Others / Independent"
                grouped.setdefault(group_name, []).append(unit)

            for name in sorted(grouped.keys()):
                groups_data.append((
                    name,
                    grouped[name],
                    "font-weight: bold; background-color: rgba(128, 128, 128, 0.10); border: 1px dashed #888;",
                ))
        return groups_data

    def _rebuild_group_widgets(self, groups_data):
        """Rebuild all group widgets (labels and tables) from scratch.
        
        Args:
            groups_data: List of (group_name, units, style) tuples.
        """
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
            table.itemDoubleClicked.connect(self.on_table_item_double_clicked)
            table.set_units(units, self.game_state)
            self._adjust_table_height(table)
            self.container_layout.addWidget(table)
            self.tables.append(table)
            self._group_widgets[name] = (c_lbl, table)

        self._group_order = [name for name, _units, _style in groups_data]

    def _update_existing_group_widgets(self, groups_data):
        """Update existing group widgets with new unit data.
        
        Rebuilds all widgets if a group name is not found in existing widgets.
        
        Args:
            groups_data: List of (group_name, units, style) tuples.
        """
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
        """Adjust the table's fixed height to fit all rows.
        
        Args:
            table: UnitTable instance to adjust.
        """
        h = table.horizontalHeader().height()
        for r in range(table.rowCount()):
            h += table.rowHeight(r)
        table.setFixedHeight(h + 2)

    def on_table_selection(self, sender_table):
        """Handle table selection changes, enforcing exclusive selection across tables.
        
        Args:
            sender_table: The UnitTable that triggered the selection change.
        """
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

    def on_table_item_double_clicked(self, item):
        """Handle double-click on a table item, emitting the associated unit.
        
        Args:
            item: QTableWidgetItem that was double-clicked.
        """
        if item is None:
            return
        unit_item = item.tableWidget().item(item.row(), 0)
        if unit_item:
            unit = unit_item.data(Qt.UserRole)
            if unit is not None:
                self.unit_double_clicked.emit(unit)
