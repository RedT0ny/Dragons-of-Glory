import sys
import yaml
import math
import os
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsScene, QGraphicsView, QGraphicsItem
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QBrush, QPen, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import Qt, QPointF, QTimer, QRectF

# Configuration for the hexagonal grid
HEX_RADIUS = 61.77 #12.2 for test_map
MAP_WIDTH = 65  # Max col observed in yaml + buffer
MAP_HEIGHT = 53  # Max row observed in yaml + buffer
SCREEN_WIDTH = 1600
SCREEN_HEIGHT = 1138
X_OFFSET = 55 # 30 for test_map
Y_OFFSET = 62 # 20 for test_map
MAP_FILE = "atlas_map.jpg" # test_map.png
LOCATION_SIZE = 60

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

class LocationItem(QGraphicsItem):
    def __init__(self, center, loc_type, is_capital, parent=None):
        super().__init__(parent)
        self.center = center
        self.loc_type = loc_type
        self.is_capital = is_capital
        self.size = LOCATION_SIZE  # Increased size for SVG visibility
        
        # Load the SVG renderer
        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icon", f"{self.loc_type}.svg")
        if os.path.exists(icon_path):
            self.renderer = QSvgRenderer(icon_path)
        else:
            self.renderer = None

    def boundingRect(self):
        """Return bounding rectangle for the location symbol."""
        size = self.size + 4  # Add some padding
        return QRectF(self.center.x() - size, self.center.y() - size, 
                      size * 2, size * 2)

    def paint(self, painter, option, widget):
        """Draw the location symbol using SVG."""
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw the SVG icon if available
        if self.renderer and self.renderer.isValid():
            rect = QRectF(self.center.x() - self.size/2, 
                         self.center.y() - self.size/2, 
                         self.size, self.size)
            self.renderer.render(painter, rect)
        else:
            # Fallback: Draw a simple circle if SVG is missing
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(self.center, self.size/4, self.size/4)

        # Draw capital indicator (Gold star/dot)
        if self.is_capital:
            painter.setBrush(QBrush(QColor(255, 215, 0)))
            painter.setPen(QPen(Qt.black, 0.5))
            # Draws capital indicator as a gold dot
            painter.drawEllipse(QPointF(self.center.x() + self.size/3, self.center.y() - self.size/3), 4, 4)

class MapViewer(QGraphicsView):
    def __init__(self):
        """Initializes scene; configures rendering and mouse interaction; loads data"""
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        
        # Enable mouse dragging
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        
        # Load data
        self.load_data()
        self.load_map_image()
        
    def load_map_image(self):
        """Load the full resolution map background image."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        map_path = os.path.join(current_dir, "..", "assets", "img", MAP_FILE)
    
        if os.path.exists(map_path):
            self.map_pixmap = QPixmap(map_path)
            if not self.map_pixmap.isNull():
                # DO NOT scale the pixmap here. Add it at full resolution.
                self.scene.addPixmap(self.map_pixmap)
                
                # Set the scene size to the actual image size
                img_rect = self.map_pixmap.rect()
                self.setSceneRect(QRectF(img_rect))
                
                # Initially scale the VIEW to fit the screen, not the image itself
                ratio = min(SCREEN_WIDTH / img_rect.width(), SCREEN_HEIGHT / img_rect.height())
                self.setTransform(QTransform.fromScale(ratio, ratio))
                return
        
    def load_data(self):
        """Load country data from YAML file."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        yaml_path = os.path.join(current_dir, "..", "data", "countries.yaml")
        
        try:
            with open(yaml_path, 'r') as f:
                self.countries_data = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"Error: Could not find {yaml_path}")
            self.countries_data = {}
            return
            
        self.hex_map = {}
        self.location_map = {}
        
        for cid, data in self.countries_data.items():
            color_hex = data.get('color', '#808080').lstrip('#')
            color_rgb = tuple(int(color_hex[i:i+2], 16) for i in (0, 2, 4))
            capital_id = data.get('capital_id')
            
            for coord in data.get('territories', []):
                if isinstance(coord, list) and len(coord) == 2:
                    self.hex_map[tuple(coord)] = color_rgb
            
            for loc_id, loc_info in data.get('locations', {}).items():
                coords = tuple(loc_info.get('coords', []))
                if coords:
                    self.location_map[coords] = {
                        'type': loc_info.get('loc_type', 'city'),
                        'is_capital': (loc_id == capital_id)
                    }
                    
    def get_hex_center(self, col, row, radius):
        """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
        x = radius * math.sqrt(3) * (col + 0.5 * (row & 1))
        y = radius * 3/2 * row
        # Adjust these offsets to align the grid to the scaled image
        return QPointF(x + X_OFFSET, y + Y_OFFSET)
        
    def draw_hex_grid(self):
        """Draw the hexagonal grid overlay."""
        # Draw empty hexes first (background grid)
        for row in range(MAP_HEIGHT):
            for col in range(MAP_WIDTH):
                center = self.get_hex_center(col, row, HEX_RADIUS)
                hex_item = HexagonItem(center, HEX_RADIUS, (200, 200, 200, 30))
                self.scene.addItem(hex_item)
                
        # Draw colored hexes (country territories)
        for (col, row), color in self.hex_map.items():
            center = self.get_hex_center(col, row, HEX_RADIUS)
            hex_item = HexagonItem(center, HEX_RADIUS, (*color, 150))
            self.scene.addItem(hex_item)
            
    def draw_locations(self):
        """Draw location symbols."""
        for coords, loc in self.location_map.items():
            center = self.get_hex_center(coords[0], coords[1], HEX_RADIUS)
            loc_item = LocationItem(center, loc['type'], loc['is_capital'])
            self.scene.addItem(loc_item)
            
    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1/zoom_factor, 1/zoom_factor)

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle("Dragons of Glory - Scaled Map Overlay")
        self.setGeometry(100, 100, SCREEN_WIDTH, SCREEN_HEIGHT)
        
        # Create map viewer
        self.viewer = MapViewer()
        
        # Draw content after a short delay (ensures scene is ready)
        QTimer.singleShot(100, self.draw_content)
        
        # Layout
        from PySide6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout()
        layout.addWidget(self.viewer)
        self.setLayout(layout)
        
    def draw_content(self):
        """Draw hex grid and locations."""
        self.viewer.draw_hex_grid()
        self.viewer.draw_locations()

def run_visualization():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_visualization()