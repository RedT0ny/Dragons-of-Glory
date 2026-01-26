import os

from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl

from src.content.config import AUDIO_DIR, MAX_TICKS
from src.gui.map_view import AnsalonMapView
from src.content.constants import WS, HL
import random

class DiplomacyMapView(AnsalonMapView):
    country_clicked = Signal(str)

    def __init__(self, game_state, parent=None, overlay_alpha=200):
        super().__init__(game_state, parent, overlay_alpha)

    def should_draw_country(self, country_id):
        """Returns neutral countries to be drawn"""
        country = self.game_state.countries.get(country_id)
        return country and country.allegiance == 'neutral'

    def mousePressEvent(self, event):
        """Emits country ID on click if neutral"""
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
        """Sets up diplomacy dialog with map and buttons"""
        super().__init__(parent)
        self.game_state = game_state
        self.setWindowTitle("Diplomacy Phase")
        self.resize(1200, 960)
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
            """
            Handles the diplomacy roll action with animation.
            On success: Closes automatically to proceed to deployment.
            On failure: Stays open so the player can see the result and click 'Close'.
            """
            # 1. Immediate UI Feedback & Blocking
            btn_ok.setDisabled(True)
            btn_cancel.setDisabled(True)  # Disable while rolling
            self.map_view.setEnabled(False)  # Lock the background map only

            # 2. Sound Effect Setup
            dice_sound = QSoundEffect(dlg)
            dice_sound.setVolume(1)
            try:
                dice_sound.setSource(QUrl.fromLocalFile(os.path.join(AUDIO_DIR, "roll_1d10.wav")))
            except Exception as e:
                print(f"Error loading dice sound: {e}")
            dice_sound.setLoopCount(1)
            dice_sound.play()

            # 3. Animation Configuration
            self.roll_ticks = 0
            actual_roll = random.randint(1, 10)
            success = actual_roll <= target_rating

            animation_timer = QTimer(dlg)

            def update_roll_visual():
                self.roll_ticks += 1

                if self.roll_ticks < MAX_TICKS:
                    fake_val = random.randint(1, 10)
                    res_lbl.setText(f"🎲 Rolling... {fake_val}")
                else:
                    # --- ANIMATION ENDS ---
                    animation_timer.stop()
                    animation_timer.deleteLater()
                    dice_sound.stop()

                    final_text = f"Rolled: {actual_roll}..."

                    if success:
                        res_lbl.setText(f"🎲 {final_text} SUCCESS!")
                        res_lbl.setStyleSheet(
                            "color: #27ae60; font-size: 18px; font-weight: bold; border: 2px solid #27ae60; padding: 5px;")

                        # Set result flag for the parent logic
                        dlg.result_success = True

                        # Update Game State Logic
                        country.allegiance = active_side
                        self.activated_country_id = country.id
                        from src.content.specs import UnitState
                        for u in self.game_state.units:
                            if u.land == country.id:
                                u.status = UnitState.READY
                                u.allegiance = active_side

                        # Success is usually followed by deployment, so auto-close is fine here
                        QTimer.singleShot(1500, lambda: (dlg.accept(), self.accept()))

                    else:
                        # --- FAILURE LOGIC ---
                        res_lbl.setText(f"🎲 {final_text} FAILURE")
                        res_lbl.setStyleSheet(
                            "color: #c0392b; font-size: 18px; font-weight: bold; border: 2px solid #c0392b; padding: 5px;")

                        # IMPORTANT: Re-enable the button and change text to "Close"
                        # We do NOT use a timer here so the user must click manually.
                        btn_cancel.setText("Close")
                        btn_cancel.setDisabled(False)

                        # Ensure clicking "Close" also closes the underlying Diplomacy Map
                        btn_cancel.clicked.disconnect()  # Remove old connection
                        btn_cancel.clicked.connect(lambda: (dlg.reject(), self.reject()))

            animation_timer.timeout.connect(update_roll_visual)
            animation_timer.start(70)

        btn_ok.clicked.connect(on_roll)
        btn_cancel.clicked.connect(dlg.reject)
        # 1. This pauses the code and actually shows the popup window to the user.
        dlg.exec()

        # 2. This runs ONLY after the popup (dlg) is closed.
        # If the roll was successful, we tell the MAIN diplomacy map to close too.
        if getattr(dlg, 'result_success', False):
            self.accept()
