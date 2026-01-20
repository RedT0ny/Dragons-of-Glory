from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer

from src.gui.map_view import AnsalonMapView
from src.content.constants import WS, HL
import random

class DiplomacyMapView(AnsalonMapView):
    country_clicked = Signal(str)

    def should_draw_country(self, country_id):
        # Only draw neutral countries
        country = self.game_state.countries.get(country_id)
        return country and country.allegiance == 'neutral'

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            items = self.scene.items(scene_pos)
            # Iterate through items to find a HexagonItem with a country_id
            from src.gui.map_items import HexagonItem
            for item in items:
                if isinstance(item, HexagonItem) and getattr(item, 'country_id', None):
                    # Check if it's a neutral country (double check)
                    if self.should_draw_country(item.country_id):
                        self.country_clicked.emit(item.country_id)
                        return # Only handle first valid country
        
        super().mousePressEvent(event)


class DiplomacyDialog(QDialog):
    def __init__(self, game_state, parent=None):
        super().__init__(parent)
        self.game_state = game_state
        self.setWindowTitle("Diplomacy Phase")
        self.resize(1000, 800)
        self.setModal(True)
        
        self.activated_country_id = None
        
        layout = QVBoxLayout(self)
        
        # Header
        lbl = QLabel("Select a Neutral Nation to Activate")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: white; background-color: #333; padding: 10px;")
        layout.addWidget(lbl)
        
        # Map View
        self.map_view = DiplomacyMapView(game_state, self)
        layout.addWidget(self.map_view)
        
        # Initialize the map rendering
        self.map_view.sync_with_model()
        
        # Connect signal
        self.map_view.country_clicked.connect(self.on_country_selected)
        
        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Pass / Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def on_country_selected(self, country_id):
        country = self.game_state.countries.get(country_id)
        if not country: return
        
        # Show Confirmation / Roll Dialog
        self.show_activation_popup(country)

    def show_activation_popup(self, country):
        active_side = self.game_state.active_player
        
        # Determine rating
        # alignment: Tuple (WS, HL)
        ws_rating = country.alignment[0]
        hl_rating = country.alignment[1]
        
        target_rating = ws_rating if active_side == WS else hl_rating
        
        # Determine color for display
        def get_color(val):
            if val <= 1: return "red"
            if val <= 4: return "orange"
            return "green"
            
        color_style = get_color(target_rating)
        
        # Custom Dialog construction
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Ally with {country.id.title()}?")
        dlg.setFixedSize(400, 250)
        
        dlg_layout = QVBoxLayout(dlg)
        
        info_lbl = QLabel(f"Attempt to activate {country.id.title()} for {active_side}?")
        info_lbl.setAlignment(Qt.AlignCenter)
        info_lbl.setStyleSheet("font-size: 14px;")
        dlg_layout.addWidget(info_lbl)
        
        stats_lbl = QLabel(f"Rating needed: {target_rating} or less")
        stats_lbl.setAlignment(Qt.AlignCenter)
        stats_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color_style};")
        dlg_layout.addWidget(stats_lbl)
        
        res_lbl = QLabel("") # Result placeholder
        res_lbl.setAlignment(Qt.AlignCenter)
        res_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        dlg_layout.addWidget(res_lbl)
        
        btn_box = QHBoxLayout()
        btn_ok = QPushButton("Attempt Roll")
        btn_cancel = QPushButton("Cancel")
        
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        dlg_layout.addLayout(btn_box)
        
        def on_roll():
            roll = random.randint(1, 10)
            success = roll <= target_rating
            
            res_text = f"Rolled: {roll}..."
            if success:
                res_lbl.setText(res_text + " Success!")
                res_lbl.setStyleSheet("color: green; font-size: 16px; font-weight: bold;")

                # Update Game State
                country.allegiance = active_side
                self.activated_country_id = country.id

                # Make units ready and update their allegiance
                from src.content.specs import UnitState
                for u in self.game_state.units:
                    if u.land == country.id:
                        u.status = UnitState.READY
                        u.allegiance = active_side

                # Close this popup after a short delay, then accept main dialog
                QTimer.singleShot(1000, dlg.accept)
                dlg.result_success = True
            else:
                res_lbl.setText(res_text + " Failure...")
                res_lbl.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")
                btn_ok.setDisabled(True)
                btn_cancel.setText("Close")
                dlg.result_success = False

        btn_ok.clicked.connect(on_roll)
        btn_cancel.clicked.connect(dlg.reject)
        
        dlg.exec()
        
        if getattr(dlg, 'result_success', False):
            self.accept()
