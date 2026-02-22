from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from src.content.audio_manager import AudioManager
from src.content.config import MAX_TICKS
from src.game.diplomacy import DiplomacyActivationService
from src.gui.map_view import AnsalonMapView


class DiplomacyMapView(AnsalonMapView):
    country_clicked = Signal(str)

    def __init__(self, game_state, parent=None, overlay_alpha=200):
        super().__init__(game_state, parent, overlay_alpha)

    def should_draw_country(self, country_id):
        """Returns neutral countries to be drawn"""
        return self.game_state.is_country_neutral(country_id)

    def mousePressEvent(self, event):
        """Emits country ID on click if neutral"""
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            items = self.scene.items(scene_pos)
            from src.gui.map_items import HexagonItem

            for item in items:
                if isinstance(item, HexagonItem) and getattr(item, "country_id", None):
                    if self.should_draw_country(item.country_id):
                        self.country_clicked.emit(item.country_id)
                        return

        super().mousePressEvent(event)


class DiplomacyDialog(QDialog):
    country_activated = Signal(str, str)  # country_id, allegiance

    def __init__(self, game_state, parent=None):
        """Sets up diplomacy dialog with map and buttons"""
        super().__init__(parent)
        self.game_state = game_state
        self.diplomacy_service = DiplomacyActivationService(game_state)
        self.setWindowTitle("Diplomacy Phase")
        self.resize(1200, 960)
        self.setModal(True)

        self.activated_country_id = None

        layout = QVBoxLayout(self)

        lbl = QLabel("Select a Neutral Nation to Activate")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: white; background-color: #333; padding: 10px;")
        layout.addWidget(lbl)

        self.map_view = DiplomacyMapView(game_state, self)
        layout.addWidget(self.map_view)

        self.map_view.sync_with_model()
        self.map_view.country_clicked.connect(self.on_country_selected)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Pass / Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def on_country_selected(self, country_id):
        country = self.game_state.countries.get(country_id)
        if not country:
            return

        self.show_activation_popup(country)

    def show_activation_popup(self, country):
        attempt = self.diplomacy_service.build_activation_attempt(country.id)
        if not attempt:
            return

        def get_color(val):
            if val <= 1:
                return "red"
            if val <= 4:
                return "orange"
            return "green"

        color_style = get_color(attempt.target_rating)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Ally with {country.id.title()}?")
        dlg.setFixedSize(400, 250)

        dlg_layout = QVBoxLayout(dlg)

        info_lbl = QLabel(f"Attempt to activate {country.id.title()} for {attempt.active_side}?")
        info_lbl.setAlignment(Qt.AlignCenter)
        info_lbl.setStyleSheet("font-size: 14px;")
        dlg_layout.addWidget(info_lbl)

        stats_text = f"Rating needed: {attempt.target_rating} or less"
        if attempt.solamnic_bonus:
            stats_text += f" (base {attempt.ws_rating} + {attempt.solamnic_bonus})"
        if attempt.event_activation_bonus:
            stats_text += f" | Event roll bonus: -{attempt.event_activation_bonus}"
        stats_lbl = QLabel(stats_text)
        stats_lbl.setAlignment(Qt.AlignCenter)
        stats_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color_style};")
        dlg_layout.addWidget(stats_lbl)

        res_lbl = QLabel("")
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
            btn_ok.setDisabled(True)
            btn_cancel.setDisabled(True)
            self.map_view.setEnabled(False)

            audio_manager = AudioManager.from_app()
            dice_sound = None
            if audio_manager:
                dice_sound = audio_manager.play_dice_roll(volume=1.0, parent=dlg)
            else:
                print("AudioManager not available; dice roll sound skipped.")

            self.roll_ticks = 0
            roll_result = self.diplomacy_service.roll_activation(
                attempt.target_rating,
                roll_bonus=attempt.event_activation_bonus,
            )

            animation_timer = QTimer(dlg)

            def update_roll_visual():
                self.roll_ticks += 1

                if self.roll_ticks < MAX_TICKS:
                    fake_val = self.diplomacy_service.roll_activation(10).roll
                    res_lbl.setText(f"Rolling... {fake_val}")
                else:
                    animation_timer.stop()
                    animation_timer.deleteLater()
                    if dice_sound:
                        dice_sound.stop()

                    if roll_result.bonus_applied:
                        final_text = (
                            f"Rolled: {roll_result.roll} "
                            f"(effective {roll_result.effective_roll} after -{roll_result.bonus_applied})..."
                        )
                    else:
                        final_text = f"Rolled: {roll_result.roll}..."

                    if roll_result.success:
                        res_lbl.setText(f"{final_text} SUCCESS!")
                        res_lbl.setStyleSheet(
                            "color: #27ae60; font-size: 18px; font-weight: bold; border: 2px solid #27ae60; padding: 5px;"
                        )

                        dlg.result_success = True

                        self.activated_country_id = country.id
                        self.country_activated.emit(country.id, attempt.active_side)

                        QTimer.singleShot(1500, lambda: (dlg.accept(), self.accept()))

                    else:
                        res_lbl.setText(f"{final_text} FAILURE")
                        res_lbl.setStyleSheet(
                            "color: #c0392b; font-size: 18px; font-weight: bold; border: 2px solid #c0392b; padding: 5px;"
                        )

                        btn_cancel.setText("Close")
                        btn_cancel.setDisabled(False)

                        btn_cancel.clicked.disconnect()
                        btn_cancel.clicked.connect(lambda: (dlg.reject(), self.reject()))

            animation_timer.timeout.connect(update_roll_visual)
            animation_timer.start(70)

        btn_ok.clicked.connect(on_roll)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec()

        if getattr(dlg, "result_success", False):
            self.accept()
