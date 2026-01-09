import math
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen, QPixmap
from PySide6.QtCore import Qt, QPointF, QRectF

from src.content.config import HEX_RADIUS, MAP_IMAGE_PATH


class HexagonItem(QGraphicsItem):
    def __init__(self, q, r, radius, color=(200, 200, 200, 100), parent=None):
        super().__init__(parent)
        self.q = q
        self.r = r
        self.radius = radius
        self.color = color
        self.is_highlighted = False # Track if this hex is a valid move
        
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

    def set_highlight(self, highlight: bool):
        self.is_highlighted = highlight
        self.update() # Triggers a repaint

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
    
        # Logic to determine base color
        # (You would pass the terrain type into the HexagonItem)
        color = QColor(*self.color)
        
        painter.setBrush(QBrush(color))
        
        # Check if the hex is coastal (we can pass this as a bool to __init__)
        if getattr(self, 'is_coastal', False):
            # Draw a thicker blue-ish border to represent the coast
            painter.setPen(QPen(QColor(0, 100, 255, 200), 3, Qt.DashLine))
        else:
            painter.setPen(QPen(QColor(50, 50, 50, 150), 1))
            
        painter.drawPath(self.path)

class UnitGraphicsItem(QGraphicsItem):
    """Visual representation of a Unit from the model."""
    def __init__(self, unit, radius, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.radius = radius

    def boundingRect(self):
        # Return a square slightly smaller than the hex
        return QRectF(-self.radius*0.6, -self.radius*0.6, self.radius*1.2, self.radius*1.2)

    def paint(self, painter, option, widget):
        # Draw the unit 'counter' (the square box)
        painter.setBrush(QBrush(QColor("blue") if self.unit.side == "Good" else QColor("red")))
        painter.setPen(QPen(Qt.black, 2))
        painter.drawRect(-15, -15, 30, 30)
        
        # Draw Attack-Defense/Movement text
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        # Assuming your Unit model has combat_rating and movement attributes
        stats_text = f"{self.unit.combat_rating}-{self.unit.movement}"
        painter.drawText(-14, 12, stats_text)

class AnsalonMapView(QGraphicsView):
    def __init__(self, game_state, parent=None): # Accept game_state
        super().__init__(parent)
        self.game_state = game_state
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        # Background Map
        self.bg_item = self.scene.addPixmap(QPixmap(MAP_IMAGE_PATH))
        self.bg_item.setZValue(-1)

    def wheelEvent(self, event):
        """
        Overrides the wheel event to provide Zooming when Ctrl is held.
        Otherwise, falls back to default scrolling behavior.
        """
        if event.modifiers() == Qt.ControlModifier:
            # Zoom factor
            zoom_in_factor = 1.25
            zoom_out_factor = 1 / zoom_in_factor

            # Determine if we zoom in or out
            if event.angleDelta().y() > 0:
                zoom_factor = zoom_in_factor
            else:
                zoom_factor = zoom_out_factor

            # Apply the scale
            self.scale(zoom_factor, zoom_factor)
            event.accept()
        else:
            # Fallback to default behavior (Vertical/Horizontal scrolling)
            super().wheelEvent(event)

    def sync_with_model(self):
        """Redraws the map based on the current GameState model."""
        self.scene.clear()
        # Re-add background using central path
        self.bg_item = self.scene.addPixmap(QPixmap(MAP_IMAGE_PATH))
        self.bg_item.setZValue(-1)

        # Get the logical grid from the model
        grid = self.game_state.map
        if grid is None:
            return

        # Check if grid is a HexGrid object and get its internal dictionary
        grid_data = grid.grid if hasattr(grid, 'grid') else {}

        for (q, r), hex_data in grid_data.items():
            # 1. Draw the Hex
            hex_item = HexagonItem(q, r, HEX_RADIUS)
            self.scene.addItem(hex_item)

            # 2. Check for units at this coordinate in the model
            units = self.game_state.get_units_at((q, r))
            for unit in units:
                self.draw_unit(unit, q, r, HEX_RADIUS)

        def highlight_movement_range(self, reachable_coords):
            """
            Loops through all HexagonItems in the scene and highlights them
            if their coordinates are in the reachable_coords list.
            """
            for item in self.scene.items():
                if isinstance(item, HexagonItem):
                    is_reachable = (item.q, item.r) in reachable_coords
                    item.set_highlight(is_reachable)

        def draw_unit(self, unit, q, r, radius):
            """Helper to place a Unit graphics item on the map."""
            unit_item = UnitGraphicsItem(unit, radius)
            # Position calculation logic (Pointy-top)
            x = radius * (math.sqrt(3) * q + math.sqrt(3)/2 * r)
            y = radius * (3/2 * r)
            unit_item.setPos(x, y)
            unit_item.setZValue(1) # Ensure units stay above hexes
            self.scene.addItem(unit_item)
