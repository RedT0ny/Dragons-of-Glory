import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QFrame, QLabel, QGridLayout, QPushButton, QTextEdit,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QStyleOptionButton, QStyle, QGraphicsScene)
from PySide6.QtCore import Qt, Signal, Slot, QRect, QRectF, QObject, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon

from src.content.config import APP_NAME, UNIT_ICON_SIZE
from src.gui.map_view import AnsalonMapView
from src.gui.map_items import UnitCounter

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
            mov_str = f"{unit.movement}"
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
    
        # Sidebar - Pass game_state for color lookups
        self.info_panel = InfoPanel(game_state=self.game_state)
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

        # Connect Map Selection to Info Panel
        self.map_view.units_clicked.connect(self.info_panel.update_unit_table)

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