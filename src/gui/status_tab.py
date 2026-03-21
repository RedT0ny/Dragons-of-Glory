from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Signal
from time import perf_counter
from collections import defaultdict
from src.content.config import DEBUG
from src.content.constants import WS, HL, NEUTRAL
from src.gui.unit_panel import AllegiancePanel
from src.content.specs import UnitColumn

class StatusTab(QWidget):
    unit_double_clicked = Signal(object)

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
        for panel in self.panels.values():
            panel.unit_double_clicked.connect(self.unit_double_clicked.emit)
        self.main_layout.addWidget(self.panels[WS])
        self.main_layout.addWidget(self.panels[HL])
        self.main_layout.addWidget(self.panels[NEUTRAL])
        self.refresh()

    def _country_counts_by_allegiance(self):
        counts = {WS: 0, HL: 0, NEUTRAL: 0}
        for country in self.game_state.countries.values():
            allegiance = getattr(country, "allegiance", None)
            if allegiance in counts:
                counts[allegiance] += 1
        return counts

    @staticmethod
    def _allegiance_label(allegiance: str) -> str:
        if allegiance == WS:
            return "Whitestone"
        if allegiance == HL:
            return "Highlord"
        if allegiance == NEUTRAL:
            return "Neutral"
        return str(allegiance).title()

    def _build_preindex(self):
        units_by_land = defaultdict(list)
        units_by_allegiance = {WS: [], HL: [], NEUTRAL: []}
        for u in self.game_state.units:
            units_by_land[getattr(u, "land", None)].append(u)
            allegiance = getattr(u, "allegiance", None)
            if allegiance in units_by_allegiance:
                units_by_allegiance[allegiance].append(u)
        return {
            "units_by_land": units_by_land,
            "units_by_allegiance": units_by_allegiance,
        }

    def _build_signature(self):
        if not self.game_state:
            return None
        countries = []
        for cid, country in self.game_state.countries.items():
            countries.append((str(cid), str(getattr(country, "allegiance", ""))))
        countries.sort()
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
                bool(getattr(u, "is_transported", False)),
                (
                    str(getattr(getattr(u, "transport_host", None), "id", "")),
                    int(getattr(getattr(u, "transport_host", None), "ordinal", 0) or 0),
                ),
            ))
        units.sort()
        return (tuple(countries), tuple(units))

    def refresh(self):
        t0 = perf_counter()
        signature = self._build_signature()
        country_counts = self._country_counts_by_allegiance()
        for allegiance, panel in self.panels.items():
            panel.set_title_text(f"{self._allegiance_label(allegiance)} ({country_counts.get(allegiance, 0)})")
        if signature == self._last_signature:
            if DEBUG:
                print("[perf] StatusTab.refresh skipped (signature unchanged)")
            return
        self._last_signature = signature
        preindexed = self._build_preindex()
        for panel in self.panels.values():
            panel.refresh(preindexed=preindexed)
        dt_ms = (perf_counter() - t0) * 1000.0
        if DEBUG:
            print(f"[perf] StatusTab.refresh rebuilt time_ms={dt_ms:.1f}")
