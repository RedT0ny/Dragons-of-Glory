from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QHeaderView, QLabel, QWidget,
                               QPushButton, QScrollArea, QFrame, QGraphicsView, QGraphicsScene, QGridLayout,
                               QAbstractItemView)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor

from src.content.specs import UnitState
from src.content.constants import WS, HL, NEUTRAL, UI_COLORS
from src.gui.map_items import UnitCounter

class UnitLabel(QLabel):
    """A clickable preview representing a unit. Uses a static Pixmap instead of a heavy QGraphicsView."""
    clicked = Signal(object) # Emits the Unit object

    def __init__(self, unit, color, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.color = color

        # UI settings for a "label-like" appearance
        self.setFixedSize(70, 70)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: transparent;")

        # Generate and set pixmap
        self.setPixmap(self._render_unit_pixmap())
        self.setCursor(Qt.PointingHandCursor)

    def _render_unit_pixmap(self):
        """Renders the UnitCounter QGraphicsItem into a QPixmap."""
        # Create a temporary scene to hold the item for rendering
        scene = QGraphicsScene()
        counter = UnitCounter(self.unit, self.color)
        scene.addItem(counter)

        # Define the target pixmap
        pixmap = QPixmap(70, 70)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Render the scene into the pixmap
        # UnitCounter is usually centered at 0,0. We need to map it to the pixmap center.
        # target rect on pixmap, source rect in scene
        target_rect = QRectF(0, 0, 70, 70)
        source_rect = QRectF(-35, -35, 70, 70)
        scene.render(painter, target_rect, source_rect)

        painter.end()
        return pixmap

    def mousePressEvent(self, event):
        # Defer the signal to prevent the widget from being destroyed while handling the event
        QTimer.singleShot(0, lambda: self.clicked.emit(self.unit))

        # Visual feedback for selection
        self.setStyleSheet("background-color: rgba(255, 255, 0, 50); border: 1px solid yellow; border-radius: 4px;")
        super().mousePressEvent(event)

    def deselect(self):
        self.setStyleSheet("background: transparent; border: none;")

class UnitSelectionDialog(QDialog):
    """Pop-up to choose between two units."""
    def __init__(self, unit1, unit2, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conscript Unit")
        self.unit1 = unit1
        self.unit2 = unit2
        self.selected_unit = None
        self.discarded_unit = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose which unit will return to service.\nThe other will be permanently eliminated."))

        h_layout = QHBoxLayout()

        # Helper to get color (simplified, grey default)
        c1 = QColor("lightgrey")
        c2 = QColor("lightgrey")

        # Unit 1 Option
        u1_layout = QVBoxLayout()
        # Note: We need to pass a color now.
        lbl1 = UnitLabel(unit1, c1)
        lbl1.setCursor(Qt.ArrowCursor) # Disable click handling of the label itself here
        btn1 = QPushButton(f"Restore {unit1.id}")
        btn1.clicked.connect(lambda: self.select_unit(unit1, unit2))
        u1_layout.addWidget(lbl1, alignment=Qt.AlignCenter)
        u1_layout.addWidget(btn1)
        h_layout.addLayout(u1_layout)

        # Unit 2 Option
        u2_layout = QVBoxLayout()
        lbl2 = UnitLabel(unit2, c2)
        lbl2.setCursor(Qt.ArrowCursor)
        btn2 = QPushButton(f"Restore {unit2.id}")
        btn2.clicked.connect(lambda: self.select_unit(unit2, unit1))
        u2_layout.addWidget(lbl2, alignment=Qt.AlignCenter)
        u2_layout.addWidget(btn2)
        h_layout.addLayout(u2_layout)

        layout.addLayout(h_layout)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def select_unit(self, kept, discarded):
        self.selected_unit = kept
        self.discarded_unit = discarded
        self.accept()


class ReplacementsDialog(QDialog):
    """
    Dialog for selecting replacements in the game.
    Allows users to choose between two units for replacement.
    The chosen unit will be ready to deploy. The other one will be destroyed.
    """
    conscription_requested = Signal(object, object)
    ready_unit_clicked = Signal(object, bool)
    finish_deployment_clicked = Signal()

    def __init__(self, game_state, view, parent=None, filter_country_id=None, allow_territory_deploy=False, invasion_mode=False):
        super().__init__(parent)
        self.game_state = game_state
        self.view = view
        self.filter_country_id = filter_country_id
        self.allow_territory_deploy = allow_territory_deploy
        self.invasion_mode = invasion_mode

        self.setWindowTitle("Replacements Pool")
        self.resize(640, 480)        # Modeless so user can interact with map
        self.setModal(False)

        self.selected_reserve_unit = None
        self.current_unit_labels = {} # Map unit_id -> UnitLabel
        self._processing_deployment = False  # Flag to prevent recursive calls

        self.setup_ui()
        self.populate_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        if self.invasion_mode:
            banner = QLabel("Invasion deployment active")
            banner.setAlignment(Qt.AlignCenter)
            banner.setStyleSheet("font-size: 14px; font-weight: bold; color: #b71c1c; background-color: #fbe9e7; padding: 6px;")
            layout.addWidget(banner)

        self.table = QTableWidget()
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalScrollBar().setSingleStep(15)
        self.table.setColumnCount(4) # Country Name, Reserve, Ready, Destroyed
        self.table.setHorizontalHeaderLabels(["Country", "Reserve (Pool)", "Ready (Deploy)", "Destroyed"])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.verticalHeader().setVisible(False)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_minimize = QPushButton("Minimize / Show Map")
        self.btn_minimize.clicked.connect(self.showMinimized)
        btn_layout.addWidget(self.btn_minimize)

        self.btn_finish = QPushButton("Finish Deployment")
        self.btn_finish.clicked.connect(self.finish_deployment_clicked.emit)
        btn_layout.addWidget(self.btn_finish)

        layout.addLayout(btn_layout)

    def populate_table(self):
        """Populates table with grouped, allegiance‑sorted country data"""
        self.table.setRowCount(0)
        self.current_unit_labels.clear()

        # Sort countries: Player Allegiance, Enemy, Neutral
        player_side = self.game_state.active_player
        enemy_side = WS if player_side == HL else HL

        # Helper set for checking valid countries
        valid_country_ids = set(self.game_state.countries.keys())

        if self.filter_country_id:
            # If filtered, we only care about this specific country
            target_c = self.game_state.countries.get(self.filter_country_id)
            if target_c:
                # Format: (Header Name, Allegiance-key-for-stateless, Country List, Is Interactive)
                # We pass None as allegiance to skip looking for stateless units in specific country view
                all_groups = [("New Ally", None, [target_c], True)]
            else:
                all_groups = []
        else:
            countries = list(self.game_state.countries.values())

            # Grouping
            player_countries = [c for c in countries if c.allegiance == player_side]
            enemy_countries = [c for c in countries if c.allegiance == enemy_side]
            neutral_countries = [c for c in countries if c.allegiance == NEUTRAL]

            all_groups = [
                ("Your Allies", player_side, player_countries, True),
                ("Enemy Forces", enemy_side, enemy_countries, False),
                ("Neutrals", NEUTRAL, neutral_countries, False)
            ]

        row_idx = 0

        for group_name, side, group_countries, is_interactive in all_groups:
            # 1. Identify "Others" (stateless units) for this side if applicable
            stateless_units = []
            if side:
                stateless_units = [
                    u for u in self.game_state.units
                    if u.allegiance == side and (not u.land or u.land not in valid_country_ids)
                ]

            if not group_countries and not stateless_units:
                continue

            # Group Header
            self.table.insertRow(row_idx)
            header_item = QTableWidgetItem(group_name)
            header_item.setBackground(QColor(50, 50, 50))
            header_item.setForeground(Qt.white)
            header_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row_idx, 0, header_item)
            self.table.setSpan(row_idx, 0, 1, 4)
            row_idx += 1

            # Render Countries
            for country in group_countries:
                self.table.insertRow(row_idx)

                # Column 0: Name
                name_item = QTableWidgetItem(country.id.title())
                self.table.setItem(row_idx, 0, name_item)

                # Retrieve units from the global state instead of the country object
                country_units = [u for u in self.game_state.units if u.land == country.id]

                self._fill_row_units(row_idx, country_units, is_interactive)
                row_idx += 1

            # Render "Others" / Stateless units
            if stateless_units:
                self.table.insertRow(row_idx)

                name_item = QTableWidgetItem("Others / Independent")
                font = name_item.font()
                font.setItalic(True)
                name_item.setFont(font)
                self.table.setItem(row_idx, 0, name_item)

                self._fill_row_units(row_idx, stateless_units, is_interactive)
                row_idx += 1

    def _fill_row_units(self, row_idx, units, is_interactive):
        """Helper to fill columns 1, 2, 3 for a given list of units."""
        # Column 1: Reserve
        reserve_units = [u for u in units if u.status == UnitState.RESERVE]
        self.set_cell_units(row_idx, 1, reserve_units, is_interactive, "reserve")

        # Column 2: Ready
        ready_units = [u for u in units if u.status == UnitState.READY]
        self.set_cell_units(row_idx, 2, ready_units, is_interactive, "ready")

        # Column 3: Destroyed
        destroyed_units = [u for u in units if u.status == UnitState.DESTROYED]
        self.set_cell_units(row_idx, 3, destroyed_units, False, "destroyed")


    def set_cell_units(self, row, col, units, interactive, category):
        """Creates a widget containing UnitLabels for the cell."""
        if not units:
            return

        container = QWidget()
        # Use QGridLayout for wrapping instead of QHBoxLayout
        layout = QGridLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.setSpacing(4)

        # Get country color from game_state lookup
        country_color = QColor(200, 200, 200)
        if units:
            country_id = units[0].land
            if country_id in self.game_state.countries:
                country_color = QColor(self.game_state.countries[country_id].color)

        # Define wrapping parameters
        cols_per_row = 4 # Number of units before wrapping to next line

        for i, unit in enumerate(units):
            # Pass color to UnitLabel constructor
            lbl = UnitLabel(unit, country_color)

            self.current_unit_labels[unit.id] = lbl
            if interactive:
                if category == "reserve":
                    lbl.clicked.connect(self.on_reserve_unit_clicked)
                elif category == "ready":
                    lbl.clicked.connect(self.on_ready_unit_clicked)
            else:
                lbl.setCursor(Qt.ForbiddenCursor)

            # Add to grid: calculate row and column index
            grid_row = i // cols_per_row
            grid_col = i % cols_per_row
            layout.addWidget(lbl, grid_row, grid_col)

        self.table.setCellWidget(row, col, container)

        # Dynamic Row Height Calculation
        num_visual_rows = (len(units) + cols_per_row - 1) // cols_per_row
        required_height = (num_visual_rows * 76) + 4 # 76px per row + margin

        current_height = self.table.rowHeight(row)
        if required_height > current_height:
            self.table.setRowHeight(row, required_height)
        elif current_height == 0:
            self.table.setRowHeight(row, max(76, required_height))


    def on_reserve_unit_clicked(self, unit):
        """Handle logic for pairing units in reserve."""
        sender_lbl = self.current_unit_labels.get(unit.id)

        if self.selected_reserve_unit is None:
            # Select first unit
            self.selected_reserve_unit = unit
            sender_lbl.setStyleSheet("border: 2px solid yellow; border-radius: 4px; background-color: rgba(255,255,0,50);")

        elif self.selected_reserve_unit == unit:
            # Deselect
            self.selected_reserve_unit = None
            sender_lbl.deselect()

        elif self.selected_reserve_unit.land == unit.land:
            # Pair found!
            self.show_conscription_choice(self.selected_reserve_unit, unit)
            # Reset selection visual
            prev_lbl = self.current_unit_labels.get(self.selected_reserve_unit.id)
            if prev_lbl: prev_lbl.deselect()
            sender_lbl.deselect()
            self.selected_reserve_unit = None
        else:
            # Different country, switch selection
            prev_lbl = self.current_unit_labels.get(self.selected_reserve_unit.id)
            if prev_lbl: prev_lbl.deselect()

            self.selected_reserve_unit = unit
            sender_lbl.setStyleSheet("border: 2px solid yellow; border-radius: 4px; background-color: rgba(255,255,0,50);")

    def show_conscription_choice(self, unit1, unit2):
        dlg = UnitSelectionDialog(unit1, unit2, self)
        if dlg.exec() == QDialog.Accepted:
            self.conscription_requested.emit(dlg.selected_unit, dlg.discarded_unit)

    def on_ready_unit_clicked(self, unit):
        """Minimize and show map targets."""
        #self.showMinimized()

        # Prevent recursive calls by checking if we're already processing
        if hasattr(self, '_processing_deployment') and self._processing_deployment:
            return
            
        try:
            self._processing_deployment = True
            self.ready_unit_clicked.emit(unit, self.allow_territory_deploy)
        finally:
            self._processing_deployment = False
    def refresh(self):
        self.populate_table()
