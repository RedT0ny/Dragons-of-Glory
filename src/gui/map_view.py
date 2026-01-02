import math
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen, QPixmap
from PySide6.QtCore import Qt, QPointF

class HexagonItem(QGraphicsItem):
    def __init__(self, q, r, radius, color=(200, 200, 200, 100), parent=None):
        super().__init__(parent)
        self.q = q
        self.r = r
        self.radius = radius
        self.color = color
        
        # Calculate pixel position (Pointy-top)
        self.x = radius * (math.sqrt(3) * q + math.sqrt(3)/2 * r)
        self.y = radius * (3/2 * r)
        self.setPos(self.x, self.y)
        
        self.path = self._create_hexagon_path()

    def _create_hexagon_path(self):
        path = QPainterPath()
        for i in range(6):
            angle_deg = 60 * i - 30
            angle_rad = math.radians(angle_deg)
            px = self.radius * math.cos(angle_rad)
            py = self.radius * math.sin(angle_rad)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        return path

    def boundingRect(self):
        return self.path.boundingRect()

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(*self.color)
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(50, 50, 50, 150), 1))
        painter.drawPath(self.path)

class AnsalonMapView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        
        # Background Map
        self.bg_item = self.scene.addPixmap(QPixmap("assets/img/DoG_map.jpg"))
        self.bg_item.setZValue(-1)

    def draw_grid(self, width, height, radius):
        """Purely visual grid for now."""
        for r in range(height):
            for q in range(width):
                # Using a simple offset-to-axial logic for the visual grid
                axial_q = q - (r // 2)
                hex_item = HexagonItem(axial_q, r, radius)
                self.scene.addItem(hex_item)
