from PySide6.QtWidgets import QWidget, QHBoxLayout
from time import perf_counter
from src.content.config import DEBUG
from src.content.constants import WS, HL, NEUTRAL
from src.gui.unit_panel import AllegiancePanel
from src.content.specs import UnitColumn

class StatusTab(QWidget):
    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self._last_signature = None
        self.init_ui()

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.columns = [
            UnitColumn.ICON,
            UnitColumn.NAME,
            UnitColumn.STATUS,
            UnitColumn.RATING,
            UnitColumn.MOVE,
            UnitColumn.POS
        ]
        self.panels = {
            WS: AllegiancePanel(self.game_state, WS, self.columns, title=WS),
            HL: AllegiancePanel(self.game_state, HL, self.columns, title=HL),
            NEUTRAL: AllegiancePanel(self.game_state, NEUTRAL, self.columns, title=NEUTRAL),
        }
        self.main_layout.addWidget(self.panels[WS])
        self.main_layout.addWidget(self.panels[HL])
        self.main_layout.addWidget(self.panels[NEUTRAL])
        self.refresh()

    def _build_signature(self):
        if not self.game_state:
            return None
        units = []
        for u in self.game_state.units:
            units.append((
                str(getattr(u, "allegiance", "")),
                str(getattr(u, "land", "")),
                str(getattr(u, "id", "")),
                int(getattr(u, "ordinal", 0) or 0),
                str(getattr(getattr(u, "status", None), "name", getattr(u, "status", ""))),
                tuple(getattr(u, "position", (None, None)) or (None, None)),
                int(getattr(u, "movement_points", getattr(u, "movement", 0)) or 0),
                bool(getattr(u, "attacked_this_turn", False)),
                int(getattr(u, "combat_rating", 0) or 0),
                int(getattr(u, "tactical_rating", 0) or 0),
            ))
        units.sort()
        return tuple(units)

    def refresh(self):
        t0 = perf_counter()
        signature = self._build_signature()
        if signature == self._last_signature:
            if DEBUG:
                print("[perf] StatusTab.refresh skipped (signature unchanged)")
            return
        self._last_signature = signature
        for panel in self.panels.values():
            panel.refresh()
        dt_ms = (perf_counter() - t0) * 1000.0
        if DEBUG:
            print(f"[perf] StatusTab.refresh rebuilt time_ms={dt_ms:.1f}")
