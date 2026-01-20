from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                                   QTableWidgetItem, QHeaderView, QLabel, QWidget, 
                                   QPushButton, QScrollArea, QFrame, QGraphicsView, QGraphicsScene)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor

from src.content.specs import UnitState, GamePhase
from src.content.constants import WS, HL, NEUTRAL, UI_COLORS
from src.gui.map_items import UnitCounter

class UnitLabel(QGraphicsView):
    """A clickable preview representing a unit using the UnitCounter class."""
    clicked = Signal(object) # Emits the Unit object

    def __init__(self, unit, parent=None):
        super().__init__(parent)
        self.unit = unit
        
        # Setup Scene
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # UI settings for a "label-like" appearance
        self.setFixedSize(70, 70)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")
        self.setRenderHint(QPainter.Antialiasing)
        
        # Add the actual UnitCounter
        # Try to find country color, default to neutral grey
        color = QColor(200, 200, 200) 
        self.counter = UnitCounter(self.unit, color)
        self.scene.addItem(self.counter)
        
        # Center the counter in the view
        self.setSceneRect(-35, -35, 70, 70)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.clicked.emit(self.unit)
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
        layout.addWidget(QLabel("Choose which unit to return to service.\nThe other will be permanently eliminated."))

        h_layout = QHBoxLayout()

        # Unit 1 Option
        u1_layout = QVBoxLayout()
        lbl1 = UnitLabel(unit1)
        lbl1.setCursor(Qt.ArrowCursor) # Disable click handling of the label itself here
        btn1 = QPushButton(f"Restore {unit1.id}")
        btn1.clicked.connect(lambda: self.select_unit(unit1, unit2))
        u1_layout.addWidget(lbl1, alignment=Qt.AlignCenter)
        u1_layout.addWidget(btn1)
        h_layout.addLayout(u1_layout)

        # Unit 2 Option
        u2_layout = QVBoxLayout()
        lbl2 = UnitLabel(unit2)
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
    def __init__(self, game_state, view, parent=None, filter_country_id=None, allow_territory_deploy=False):
        super().__init__(parent)
        self.game_state = game_state
        self.view = view # We need access to map view for "Ready" unit clicks
        self.filter_country_id = filter_country_id
        self.allow_territory_deploy = allow_territory_deploy

        self.setWindowTitle("Replacements Pool")
        self.resize(1000, 600)        # Modeless so user can interact with map
        self.setModal(False)

        self.selected_reserve_unit = None
        self.current_unit_labels = {} # Map unit_id -> UnitLabel

        self.setup_ui()
        self.populate_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
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

        layout.addLayout(btn_layout)

    def populate_table(self):
        """Populates table with grouped, allegiance‑sorted country data"""
        self.table.setRowCount(0)
        self.current_unit_labels.clear()

        # Sort countries: Player Allegiance, Enemy, Neutral
        player_side = self.game_state.active_player
        enemy_side = WS if player_side == HL else HL

        if self.filter_country_id:
            # If filtered, we only care about this specific country
            target_c = self.game_state.countries.get(self.filter_country_id)
            if target_c:
                all_groups = [("New Ally", [target_c], True)]
            else:
                all_groups = []
        else:
            countries = list(self.game_state.countries.values())

            # Grouping
            player_countries = [c for c in countries if c.allegiance == player_side]
            enemy_countries = [c for c in countries if c.allegiance == enemy_side]
            neutral_countries = [c for c in countries if c.allegiance == NEUTRAL]

            all_groups = [
                ("Your Allies", player_countries, True),
                ("Enemy Forces", enemy_countries, False),
                ("Neutrals", neutral_countries, False) # Can't replace neutrals typically until active
            ]

        row_idx = 0
        # Populates table with country groups and unit counts
        for group_name, group_countries, is_interactive in all_groups:
            if not group_countries: continue

            # Group Header
            self.table.insertRow(row_idx)
            header_item = QTableWidgetItem(group_name)
            header_item.setBackground(QColor(50, 50, 50))
            header_item.setForeground(Qt.white)
            header_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row_idx, 0, header_item)
            self.table.setSpan(row_idx, 0, 1, 4)
            row_idx += 1

            for country in group_countries:
                self.table.insertRow(row_idx)

                # Column 0: Name
                name_item = QTableWidgetItem(country.id.title())
                self.table.setItem(row_idx, 0, name_item)

                # Retrieve units from the global state instead of the country object
                country_units = [u for u in self.game_state.units if u.land == country.id]

                # Column 1: Reserve
                reserve_units = [u for u in country_units if u.status == UnitState.RESERVE]
                self.set_cell_units(row_idx, 1, reserve_units, is_interactive, "reserve")

                # Column 2: Ready
                ready_units = [u for u in country_units if u.status == UnitState.READY]
                self.set_cell_units(row_idx, 2, ready_units, is_interactive, "ready")

                # Column 3: Destroyed
                destroyed_units = [u for u in country_units if u.status == UnitState.DESTROYED]
                self.set_cell_units(row_idx, 3, destroyed_units, False, "destroyed")

                row_idx += 1

    def set_cell_units(self, row, col, units, interactive, category):
        """Creates a widget containing UnitLabels for the cell."""
        if not units:
            return

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setAlignment(Qt.AlignLeft)

        # Get country color from map_view lookup if possible
        country_color = QColor(200, 200, 200)
        if units:
            country_color = self.view.country_colors.get(units[0].land, country_color)

        for unit in units:
            lbl = UnitLabel(unit)
            # Update the counter color inside the label
            lbl.counter.color = country_color

            self.current_unit_labels[unit.id] = lbl
            if interactive:
                if category == "reserve":
                    lbl.clicked.connect(self.on_reserve_unit_clicked)
                elif category == "ready":
                    lbl.clicked.connect(self.on_ready_unit_clicked)
            else:
                lbl.setCursor(Qt.ForbiddenCursor)

            layout.addWidget(lbl)

        self.table.setCellWidget(row, col, container)
        # Adjust row height if needed
        self.table.setRowHeight(row, 70)

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
            # Apply Logic
            dlg.selected_unit.status = UnitState.READY
            dlg.discarded_unit.status = UnitState.DESTROYED
            self.refresh()

    def on_ready_unit_clicked(self, unit):
        """Minimize and show map targets."""
        self.showMinimized()

        # Center map on country capital or units
        country = self.game_state.countries.get(unit.land)
        if country:
            # Logic to find valid deployment hexes
            valid_hexes = []

            if self.allow_territory_deploy:
                # Allowed anywhere in territory (for newly activated countries)
                # We convert set of tuples to list
                valid_hexes = list(country.territories)
            else:
                # Cities or Fortresses of the country, not enemy occupied
                for loc_id, loc in country.locations.items():
                    # Assuming simple check for now. TODO: Check occupation
                    valid_hexes.append(loc.coords)

            self.view.highlight_deployment_targets(valid_hexes, unit)

    def refresh(self):
        self.populate_table()
