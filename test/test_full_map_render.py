import sys
import math
import os
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsScene, QGraphicsView, QGraphicsItem
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen, QPixmap
from PySide6.QtCore import Qt, QPointF, QTimer, QRectF

# Add src to path to use existing loaders
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.content.config import HEX_RADIUS, MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET, SCREEN_WIDTH, SCREEN_HEIGHT

# Colors for hexsides
HEXSIDE_COLORS = {
    "river": QColor(100, 149, 237, 200),      # Cornflower Blue
    "deep_river": QColor(0, 0, 139, 255),     # Dark Blue
    "mountain": QColor(139, 69, 19, 200),     # Saddle Brown
    "pass": QColor(255, 215, 0, 255),         # Gold
    "bridge": QColor(255, 69, 0, 255)         # Red-Orange
}

# Define Terrain Visuals
TERRAIN_VISUALS = {
    "grassland": {"color": QColor(238, 244, 215), "pattern": Qt.SolidPattern},
    "steppe": {"color": QColor(180, 190, 100), "pattern": Qt.HorPattern},
    "forest": {"color": QColor(34, 139, 34), "pattern": Qt.Dense6Pattern},
    "jungle": {"color": QColor(0, 85, 0), "pattern": Qt.Dense5Pattern},
    "mountain": {"color": QColor(139, 115, 85), "pattern": Qt.CrossPattern},
    "swamp": {"color": QColor(85, 107, 47), "pattern": Qt.BDiagPattern},
    "desert": {"color": QColor(244, 164, 96), "pattern": Qt.Dense7Pattern},
    "ocean": {"color": QColor(135, 206, 250), "pattern": Qt.SolidPattern},
    "maelstrom": {"color": QColor(130, 9, 9), "pattern": Qt.Dense4Pattern},
    "glacier": {"color": QColor(231, 173, 255), "pattern": Qt.DiagCrossPattern},
}

class HexagonItem(QGraphicsItem):
    def __init__(self, center, radius, color, terrain_type="grassland", parent=None):
        super().__init__(parent)
        self.center = center
        self.radius = radius
        # Ensure color is a QColor object even if a tuple is passed
        self.color = QColor(*color) if isinstance(color, (tuple, list)) else color
        self.terrain_type = terrain_type
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
        # Draw terrain base and pattern
        visual = TERRAIN_VISUALS.get(self.terrain_type, TERRAIN_VISUALS["grassland"])
        
        # Layer 1: Terrain Color + Pattern
        base_brush = QBrush(visual["color"], visual["pattern"])
        painter.setBrush(base_brush)
        painter.setPen(QPen(QColor(100, 100, 100, 40), 0.5))
        painter.drawPath(self.path)

        # Layer 2: Country Overlay (if applicable)
        # Now alpha() will work because self.color is guaranteed to be a QColor
        if self.color.alpha() > 0:
            painter.setBrush(QBrush(self.color))
            painter.setPen(Qt.NoPen)
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

    def get_hex_center(self, col, row):
        """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
        x = HEX_RADIUS * math.sqrt(3) * (col + 0.5 * (row & 1))
        y = HEX_RADIUS * 3/2 * row
        return QPointF(x + X_OFFSET, y + Y_OFFSET)

    def load_all_data(self):
        # Use centralized loaders from src.content.loader
        from src.content import loader
        from src.content.config import COUNTRIES_DATA, MAP_CONFIG_DATA, MAP_TERRAIN_DATA
        
        # 1. Load Countries
        self.country_specs = loader.load_countries_yaml(COUNTRIES_DATA)
    
        # 2. Load Map Config (using the new structured loader)
        self.map_cfg = loader.load_map_config(MAP_CONFIG_DATA)
    
        # 3. Load Terrain CSV
        self.terrain_data = loader.load_terrain_csv(MAP_TERRAIN_DATA)

    def draw_map(self):
        # Draw all hexes with terrain from CSV
        for row in range(MAP_HEIGHT):
            for col in range(MAP_WIDTH):
                center = self.get_hex_center(col, row)
                # Look up terrain from our new CSV data
                t_type = self.terrain_data.get(f"{col},{row}", "ocean")
                self.scene.addItem(HexagonItem(center, HEX_RADIUS, QColor(0,0,0,0), terrain_type=t_type))

        # Overlay Country territories
        for cid, spec in self.country_specs.items():
            color = QColor(spec.color)
            rgba = QColor(color.red(), color.green(), color.blue(), 100)
            for col, row in spec.territories:
                center = self.get_hex_center(col, row)
                # Ensure we pass the terrain type here so patterns show through the color
                t_type = self.terrain_data.get(f"{col},{row}", "grassland")
                self.scene.addItem(HexagonItem(center, HEX_RADIUS, rgba, terrain_type=t_type))

        # Draw Hexsides (Rivers, Mountains, etc)
        hexsides = self.map_cfg.hexsides
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
        # Computes vertex from center using trigonometric functions
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
