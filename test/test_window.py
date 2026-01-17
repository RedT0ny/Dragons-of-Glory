import sys
import yaml
import math
import os
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsScene, QGraphicsView, QGraphicsItem
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QBrush, QPen, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import Qt, QPointF, QTimer, QRectF
from src.content.config import HEX_RADIUS, MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET, SCREEN_WIDTH, SCREEN_HEIGHT

class HexagonItem(QGraphicsItem):
    def __init__(self, center, radius, color, parent=None):
        super().__init__(parent)
        self.center = center
        self.radius = radius
        self.color = color
        self.createPolygon()

    def createPolygon(self):
        """Create hexagon polygon points for pointy-top hexagon."""
        self.points = []
        for i in range(6):
            angle_deg = 60 * i - 30
            angle_rad = math.radians(angle_deg)
            x = self.center.x() + self.radius * math.cos(angle_rad)
            y = self.center.y() + self.radius * math.sin(angle_rad)
            self.points.append(QPointF(x, y))

        # Create QPainterPath
        self.path = QPainterPath()
        self.path.moveTo(self.points[0])
        for point in self.points[1:]:
            self.path.lineTo(point)
        self.path.closeSubpath()

    def boundingRect(self):
        """Return the bounding rectangle of the hexagon."""
        return self.path.boundingRect()

    def paint(self, painter, option, widget):
        """Paint the hexagon with fill and border."""
        # Fill hexagon
        if len(self.color) == 4:  # RGBA
            brush_color = QColor(*self.color)
        else:  # RGB
            brush_color = QColor(*self.color, 255)

        painter.setBrush(QBrush(brush_color))
        painter.setPen(QPen(QColor(40, 40, 40), 1))
        painter.drawPath(self.path)


class TestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dragons of Glory - Global Map Verification")
        self.resize(SCREEN_WIDTH, SCREEN_HEIGHT)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
