import sys
import os
import yaml
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QTextEdit, QSplitter, QPushButton,
    QDialog, QSizePolicy
)
from PySide6.QtGui import QFont, QColor, QPalette, QPixmap
from PySide6.QtCore import Qt, QSize

from src.content.config import DATA_DIR, IMAGES_DIR

ALLEGIANCE_COLORS = {
    "whitestone": QColor("#2b7be4"),
    "highlord":   QColor("#d43d3d"),
}
ALLEGIANCE_LABELS = {
    "whitestone": "Whitestone",
    "highlord":   "Highlord",
}
TYPE_COLORS = {
    "diplomacy": QColor("#4caf50"),
    "artifact":  QColor("#ff9800"),
    "units":     QColor("#9c27b0"),
    "bonus":     QColor("#00bcd4"),
    "resource":  QColor("#8bc34a"),
}

def _palette_color(widget, role, alpha=255):
    color = widget.palette().color(role)
    if alpha < 255:
        color.setAlpha(alpha)
    return color.name(QColor.HexArgb)

def test_load_events():
    path = os.path.join(DATA_DIR, "events.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    events = []
    for eid, data in raw.items():
        turn = data.get("turn", 0)
        events.append({
            "id": eid,
            "turn": turn,
            "type": data.get("type", "unknown"),
            "allegiance": data.get("allegiance", "none"),
            "description": data.get("description", ""),
            "picture": data.get("picture", ""),
            "effects": data.get("effects", {}),
            "max_occurrences": data.get("max_occurrences"),
            "requirements": data.get("requirements", []),
        })
    events.sort(key=lambda e: (e["turn"], e["id"]))
    return events


class EventDetailDialog(QDialog):
    def __init__(self, event, parent=None):
        super().__init__(parent)
        self.setWindowTitle(event["id"].replace("_", " ").title())
        self.resize(700, 500)
        layout = QVBoxLayout(self)

        title = QLabel(event["id"].replace("_", " ").title())
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        meta = QHBoxLayout()
        turn_label = QLabel(f"Turn: {event['turn']}")
        turn_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        meta.addWidget(turn_label)
        type_label = QLabel(f"Type: {event['type']}")
        tc = TYPE_COLORS.get(event["type"]) or QColor(_palette_color(self, QPalette.Mid))
        type_label.setStyleSheet(f"font-size: 14px; color: {tc.name()}; font-weight: bold;")
        meta.addWidget(type_label)
        if event["allegiance"] != "none":
            ali = event["allegiance"]
            c = ALLEGIANCE_COLORS.get(ali) or QColor(_palette_color(self, QPalette.Mid))
            ali_label = QLabel(f"Allegiance: {ALLEGIANCE_LABELS.get(ali, ali)}")
            ali_label.setStyleSheet(f"font-size: 14px; color: {c.name()}; font-weight: bold;")
            meta.addWidget(ali_label)
        meta.addStretch()
        layout.addLayout(meta)

        if event["picture"]:
            img_path = os.path.join(IMAGES_DIR, event["picture"])
            if os.path.exists(img_path):
                img_label = QLabel()
                pix = QPixmap(img_path)
                img_label.setPixmap(pix.scaled(600, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                img_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(img_label)

        desc = QTextEdit()
        desc.setReadOnly(True)
        desc.setHtml(f"<p style='font-size:14px; line-height:1.6;'>{event['description'].replace(chr(10), '<br>')}</p>")
        layout.addWidget(desc)

        effects_text = ", ".join(f"{k}: {v}" for k, v in event["effects"].items())
        if effects_text:
            eff = QLabel(f"Effects: {effects_text}")
            eff.setStyleSheet("font-size: 13px; font-style: italic;")
            layout.addWidget(eff)

        if event.get("requirements"):
            req_text = "; ".join(f"{r['type']}: {r['id']}" for r in event["requirements"])
            req = QLabel(f"Requirements: {req_text}")
            req.setStyleSheet("font-size: 13px;")
            layout.addWidget(req)

        if event.get("max_occurrences"):
            occ = QLabel(f"Max occurrences: {event['max_occurrences']}")
            occ.setStyleSheet("font-size: 13px;")
            layout.addWidget(occ)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)


class TimelineWidget(QWidget):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.setup_ui()

    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        self.layout = QVBoxLayout(container)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(0)

        title = QLabel("Event Timeline")
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("padding: 20px;")
        self.layout.addWidget(title)

        self.populate()

    def populate(self):
        if not self.events:
            return

        max_turn = max(e["turn"] for e in self.events)
        min_turn = min(e["turn"] for e in self.events)

        by_turn = {}
        for e in self.events:
            by_turn.setdefault(e["turn"], []).append(e)

        for turn in range(min_turn, max_turn + 1):
            turn_events = by_turn.get(turn, [])

            row = QHBoxLayout()
            row.setSpacing(16)

            turn_marker = QWidget()
            turn_marker.setFixedWidth(60)
            turn_marker_layout = QVBoxLayout(turn_marker)
            turn_marker_layout.setContentsMargins(0, 0, 0, 0)
            turn_marker_layout.setAlignment(Qt.AlignTop)

            turn_label = QLabel(str(turn))
            turn_label.setAlignment(Qt.AlignCenter)
            turn_font = QFont()
            turn_font.setPointSize(16)
            turn_font.setBold(True)
            turn_label.setFont(turn_font)
            turn_label.setStyleSheet("padding: 6px 0;")
            turn_marker_layout.addWidget(turn_label)

            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFixedWidth(2)
            if turn_events:
                line.setStyleSheet(f"background-color: {_palette_color(self, QPalette.Mid)};")
            else:
                line.setStyleSheet(f"background-color: {_palette_color(self, QPalette.Mid, 120)};")
            turn_marker_layout.addWidget(line, stretch=1)

            row.addWidget(turn_marker, alignment=Qt.AlignTop)

            if turn_events:
                events_widget = QWidget()
                events_layout = QHBoxLayout(events_widget)
                events_layout.setContentsMargins(0, 0, 0, 0)
                events_layout.setSpacing(12)

                for ev in turn_events:
                    card = self.test_create_event_card(ev)
                    events_layout.addWidget(card)

                events_layout.addStretch()
                row.addWidget(events_widget, stretch=1)
            else:
                spacer = QWidget()
                spacer.setMinimumHeight(40)
                row.addWidget(spacer, stretch=1)

            self.layout.addLayout(row)

            if turn < max_turn:
                connector = QFrame()
                connector.setFrameShape(QFrame.HLine)
                connector.setFixedHeight(1)
                connector.setStyleSheet(f"background-color: {_palette_color(self, QPalette.Mid, 120)}; margin-left: 76px;")
                self.layout.addWidget(connector)

    def test_create_event_card(self, event):
        card = QFrame()
        card.setFixedWidth(220)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {self.palette().color(QPalette.Window).name()};
                border-radius: 8px;
                border: 1px solid {self.palette().color(QPalette.Mid).name()};
            }}
            QFrame:hover {{
                border: 1px solid {self.palette().color(QPalette.Highlight).name()};
            }}
        """)
        card.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)

        type_dot = QLabel()
        type_dot.setFixedSize(10, 10)
        tc = TYPE_COLORS.get(event["type"]) or QColor(_palette_color(self, QPalette.Mid))
        type_dot.setStyleSheet(f"background-color: {tc.name()}; border-radius: 5px;")
        header.addWidget(type_dot)

        type_label = QLabel(event["type"])
        type_label.setStyleSheet(f"color: {tc.name()}; font-size: 11px; font-weight: bold;")
        header.addWidget(type_label)

        header.addStretch()

        if event["allegiance"] != "none":
            ac = ALLEGIANCE_COLORS.get(event["allegiance"]) or QColor(_palette_color(self, QPalette.Mid))
            ali_dot = QLabel()
            ali_dot.setFixedSize(8, 8)
            ali_dot.setStyleSheet(f"background-color: {ac.name()}; border-radius: 4px;")
            header.addWidget(ali_dot)

        layout.addLayout(header)

        name = QLabel(event["id"].replace("_", " ").title())
        name.setWordWrap(True)
        name_font = QFont()
        name_font.setPointSize(11)
        name_font.setBold(True)
        name.setFont(name_font)
        layout.addWidget(name)

        desc_preview = event["description"].replace("\n", " ").strip()
        if len(desc_preview) > 80:
            desc_preview = desc_preview[:77] + "..."
        preview = QLabel(desc_preview)
        preview.setWordWrap(True)
        preview.setStyleSheet("font-size: 10px;")
        preview.setFixedHeight(36)
        layout.addWidget(preview)

        effects_text = ", ".join(str(v) for v in event["effects"].values())
        if effects_text:
            eff = QLabel(f"→ {effects_text}")
            eff.setStyleSheet("font-size: 11px;")
            layout.addWidget(eff)

        card.mousePressEvent = lambda e, ev=event: self.test_show_event_detail(ev)
        return card

    def test_show_event_detail(self, event):
        dlg = EventDetailDialog(event, self)
        dlg.exec()


class TimelineWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dragons of Glory - Event Timeline Viewer")
        self.resize(1200, 800)
        events = test_load_events()
        self.timeline = TimelineWidget(events)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.timeline)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TimelineWindow()
    window.show()
    sys.exit(app.exec())
