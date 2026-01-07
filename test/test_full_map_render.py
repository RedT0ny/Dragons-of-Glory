import sys
import math
import os
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsScene, QGraphicsView, QGraphicsItem
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen
from PySide6.QtCore import Qt, QPointF, QTimer, QRectF

# Add src to path to use existing loaders
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.content.loader import load_countries_yaml, load_data

# Configuration from your map_config.yaml logic
HEX_RADIUS = 11.15
MAP_WIDTH = 65
MAP_HEIGHT = 53
SCREEN_WIDTH = 1400
SCREEN_HEIGHT = 900
X_OFFSET = 30
Y_OFFSET = 30

# Colors for hexsides
HEXSIDE_COLORS = {
    "river": QColor(100, 149, 237, 200),      # Cornflower Blue
    "deep_river": QColor(0, 0, 139, 255),     # Dark Blue
    "mountain": QColor(139, 69, 19, 200),     # Saddle Brown
    "pass": QColor(255, 215, 0, 255),         # Gold
    "bridge": QColor(255, 69, 0, 255)         # Red-Orange
}

class HexagonItem(QGraphicsItem):
    def __init__(self, center, radius, color, parent=None):
        super().__init__(parent)
        self.center = center
        self.radius = radius
        self.color = color
        self.points = []
        
        # Create pointy-top hexagon path
        self.path = QPainterPath()
        for i in range(6):
            angle_rad = math.radians(60 * i - 30)
            x = self.center.x() + self.radius * math.cos(angle_rad)
            y = self.center.y() + self.radius * math.sin(angle_rad)
            pt = QPointF(x, y)
            self.points.append(pt)
            if i == 0: self.path.moveTo(pt)
            else: self.path.lineTo(pt)
        self.path.closeSubpath()

    def boundingRect(self):
        return self.path.boundingRect()

    def paint(self, painter, option, widget):
        painter.setBrush(QBrush(QColor(*self.color)))
        painter.setPen(QPen(QColor(100, 100, 100, 50), 0.5))
        painter.drawPath(self.path)

class HexsideItem(QGraphicsItem):
    def __init__(self, start_pt, end_pt, side_type):
        super().__init__()
        self.start_pt = start_pt
        self.end_pt = end_pt
        self.color = HEXSIDE_COLORS.get(side_type, Qt.black)
        self.width = 3 if "river" in side_type or side_type == "mountain" else 5

    def boundingRect(self):
        return QRectF(self.start_pt, self.end_pt).normalized().adjusted(-5, -5, 5, 5)

    def paint(self, painter, option, widget):
        pen = QPen(self.color, self.width, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(self.start_pt, self.end_pt)

class MapViewer(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        
        self.load_all_data()

    def load_all_data(self):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        
        # 1. Load Countries and territories
        self.country_specs = load_countries_yaml(os.path.join(data_dir, "countries.yaml"))
        
        # 2. Load Map Config (Hexsides and Special Locations)
        self.map_cfg = load_data(os.path.join(data_dir, "map_config.yaml"))
        
    def get_hex_center(self, col, row):
        x = HEX_RADIUS * math.sqrt(3) * (col + 0.5 * (row & 1))
        y = HEX_RADIUS * 3/2 * row
        return QPointF(x + X_OFFSET, y + Y_OFFSET)

    def draw_map(self):
        # Draw all hexes first
        for row in range(MAP_HEIGHT):
            for col in range(MAP_WIDTH):
                center = self.get_hex_center(col, row)
                self.scene.addItem(HexagonItem(center, HEX_RADIUS, (240, 240, 240, 255)))

        # Overlay Country territories
        for cid, spec in self.country_specs.items():
            color = QColor(spec.color)
            rgba = (color.red(), color.green(), color.blue(), 100)
            for col, row in spec.territories:
                center = self.get_hex_center(col, row)
                self.scene.addItem(HexagonItem(center, HEX_RADIUS, rgba))

        # Draw Hexsides (Rivers, Mountains, etc)
        hexsides = self.map_cfg.get('master_map', {}).get('hexsides', {})
        for side_type, entries in hexsides.items():
            for col, row, direction in entries:
                center = self.get_hex_center(col, row)
                # Map direction string to point index (E=0, NE=1, NW=2, W=3, SW=4, SE=5)
                # Pointy top indexing: 0 is at 30 deg (right-ish)
                dir_map = {"E": 0, "NE": 5, "NW": 4, "W": 3, "SW": 2, "SE": 1}
                idx = dir_map.get(direction)
                
                if idx is not None:
                    # Logic: A hexside is the line between two vertices
                    # For pointy top: E is between point[0] and point[1]
                    p1 = self.get_vertex(center, idx)
                    p2 = self.get_vertex(center, (idx + 1) % 6)
                    self.scene.addItem(HexsideItem(p1, p2, side_type))

    def get_vertex(self, center, i):
        angle_rad = math.radians(60 * i - 30)
        return QPointF(center.x() + HEX_RADIUS * math.cos(angle_rad),
                       center.y() + HEX_RADIUS * math.sin(angle_rad))

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

class TestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dragons of Glory - Global Map Verification")
        self.resize(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.viewer = MapViewer()
        
        from PySide6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(self)
        layout.addWidget(self.viewer)
        
        QTimer.singleShot(100, self.viewer.draw_map)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
