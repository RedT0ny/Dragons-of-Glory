import math
import os

from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen, QPixmap
from PySide6.QtCore import Qt, QPointF, QRectF

from src.content.config import (DEBUG, HEX_RADIUS, MAP_IMAGE_PATH, COUNTRIES_DATA, MAP_CONFIG_DATA, MAP_TERRAIN_DATA,
                                MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET, WS, LOCATION_SIZE, ICONS_DIR)
from src.content import loader

# Define Terrain Visuals
TERRAIN_VISUALS = {
    "grassland": {"color": QColor(238, 244, 215), "pattern": Qt.Dense7Pattern},
    "steppe": {"color": QColor(180, 190, 100), "pattern": Qt.Dense7Pattern},
    "forest": {"color": QColor(34, 139, 34), "pattern": Qt.Dense7Pattern},
    "jungle": {"color": QColor(0, 85, 0), "pattern": Qt.Dense7Pattern},
    "mountain": {"color": QColor(139, 115, 85), "pattern": Qt.Dense7Pattern},
    "swamp": {"color": QColor(85, 107, 47), "pattern": Qt.Dense7Pattern},
    "desert": {"color": QColor(244, 164, 96), "pattern": Qt.Dense7Pattern},
    "ocean": {"color": QColor(135, 206, 250), "pattern": Qt.Dense7Pattern},
    "maelstrom": {"color": QColor(130, 9, 9), "pattern": Qt.Dense7Pattern},
    "glacier": {"color": QColor(231, 173, 255), "pattern": Qt.Dense7Pattern},
}

# Colors for hexsides
HEXSIDE_COLORS = {
    "river": QColor(100, 149, 237, 200),
    "deep_river": QColor(0, 0, 139, 255),
    "mountain": QColor(139, 69, 19, 200),
    "pass": QColor(255, 215, 0, 255),
    "bridge": QColor(255, 69, 0, 255)
}

class HexagonItem(QGraphicsItem):
    def __init__(self, center, radius, color, terrain_type="grassland", coastal_directions=None, pass_directions=None, parent=None):
        super().__init__(parent)
        self.center = center
        self.radius = radius
        # Ensure color is a QColor object even if a tuple is passed
        self.color = QColor(*color) if isinstance(color, (tuple, list)) else color
        self.terrain_type = terrain_type
        self.coastal_directions = coastal_directions or []
        self.pass_directions = pass_directions or []
        self.is_highlighted = False # Track if this hex is a valid move
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

    def set_highlight(self, highlight: bool):
        self.is_highlighted = highlight
        self.update()

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw terrain base and pattern
        visual = TERRAIN_VISUALS.get(self.terrain_type, TERRAIN_VISUALS["grassland"])
        
        # Layer 1: Terrain Color + Pattern
        if DEBUG:
            base_brush = QBrush(visual["color"], visual["pattern"])
            painter.setBrush(base_brush)
            painter.setPen(QPen(QColor(100, 100, 100, 40), 0.5))
            painter.drawPath(self.path)

        # Layer 2: Country Overlay (if applicable)
        if self.color.alpha() > 0:
            painter.setBrush(QBrush(self.color))
            painter.setPen(Qt.NoPen)
            painter.drawPath(self.path)
    
        # Layer 3: Coastal Wedges (if this is a coastal hex)
        if DEBUG:
            if self.coastal_directions:
                self.draw_coastal_wedges(painter)

        # Layer 4: Mountain Passes (if this is a mountain hex)
        if self.pass_directions:
            self.draw_mountain_passes(painter)

        # Layer 6: Highlight if selected/reachable
        if self.is_highlighted:
            painter.setBrush(QBrush(QColor(255, 255, 0, 100)))
            painter.setPen(QPen(QColor(255, 255, 0), 2))
            painter.drawPath(self.path)

    def draw_coastal_wedges(self, painter):
        """Draw triangular wedges for all sea hexsides."""
        ocean_color = TERRAIN_VISUALS["ocean"]["color"]
        wedge_color = QColor(ocean_color.red(), ocean_color.green(), ocean_color.blue(), 100)
    
        for direction_idx in self.coastal_directions:
            # Get the two vertices of the hexside facing the sea
            v1 = self.points[direction_idx]
            v2 = self.points[(direction_idx + 1) % 6]
        
            # Create a triangular wedge from center to the two vertices
            wedge_path = QPainterPath()
            wedge_path.moveTo(self.center)
            wedge_path.lineTo(v1)
            wedge_path.lineTo(v2)
            wedge_path.closeSubpath()
        
            painter.setBrush(QBrush(wedge_color))
            painter.setPen(Qt.NoPen)
            painter.drawPath(wedge_path)

    def draw_mountain_passes(self, painter):
        """Draw triangular wedges for all sea hexsides."""
        pass_color = HEXSIDE_COLORS["pass"]

        for direction_idx in self.pass_directions:
            # Get the two vertices of the hexside facing the sea
            v1 = self.points[direction_idx]
            v2 = self.points[(direction_idx + 1) % 6]

            # Calculate the center of this hexside
            hexside_center = QPointF((v1.x() + v2.x()) / 2, (v1.y() + v2.y()) / 2)

            # Vector from current center to hexside center
            vector = QPointF(hexside_center.x() - self.center.x(),
                             hexside_center.y() - self.center.y())

            # Extend the vector to get to adjacent hex center
            # For regular hexagons, adjacent center is 2x the distance
            adjacent_center = QPointF(self.center.x() + 2 * vector.x(),
                                      self.center.y() + 2 * vector.y())

            # Create the line path
            line_path = QPainterPath()
            line_path.moveTo(self.center)
            line_path.lineTo(hexside_center)
            line_path.lineTo(adjacent_center)

            # Draw the line
            pen = QPen(pass_color, 8)
            pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.drawPath(line_path)

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


class LocationItem(QGraphicsItem):
    def __init__(self, center, loc_id, loc_type, is_capital, parent=None):
        super().__init__(parent)
        self.center = center
        self.loc_id = loc_id
        self.loc_type = loc_type
        self.is_capital = is_capital
        self.size = LOCATION_SIZE  # Increased size for SVG visibility

        # Load the SVG renderer
        icon_path = os.path.join(ICONS_DIR, f"{self.loc_type}.svg")
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
            rect = QRectF(self.center.x() - self.size / 2,
                          self.center.y() - self.size / 2,
                          self.size, self.size)
            self.renderer.render(painter, rect)
        else:
            # Fallback: Draw a simple circle if SVG is missing
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(self.center, self.size / 4, self.size / 4)

        # Draw capital indicator (Gold star/dot)
        if self.is_capital:
            painter.setBrush(QBrush(QColor(255, 215, 0)))
            painter.setPen(QPen(Qt.black, 0.5))
            # Draws capital indicator as a gold dot
            painter.drawEllipse(QPointF(self.center.x() + self.size / 3, self.center.y() - self.size / 3), 4, 4)


class UnitGraphicsItem(QGraphicsItem):
    """Visual representation of a Unit from the model."""
    def __init__(self, unit, radius, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.radius = radius

    def boundingRect(self):
        return QRectF(-self.radius*0.6, -self.radius*0.6, self.radius*1.2, self.radius*1.2)

    def paint(self, painter, option, widget):
        painter.setBrush(QBrush(QColor("blue") if self.unit.allegiance == WS else QColor("red")))
        painter.setPen(QPen(Qt.black, 2))
        painter.drawRect(-15, -15, 30, 30)
    
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        stats_text = f"{self.unit.combat_rating}-{self.unit.movement}"
        painter.drawText(-14, 12, stats_text)


class AnsalonMapView(QGraphicsView):
    def __init__(self, game_state, parent=None):
        super().__init__(parent)
        self.game_state = game_state
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        # Load map data
        self.load_all_data()

        # Background Map
        self.bg_item = self.scene.addPixmap(QPixmap(MAP_IMAGE_PATH))
        self.bg_item.setZValue(-1)

    def load_all_data(self):
        """Load all map configuration data."""
        self.country_specs = loader.load_countries_yaml(COUNTRIES_DATA)
        self.map_cfg = loader.load_map_config(MAP_CONFIG_DATA)
        self.location_map = self.create_location_map()
        self.terrain_data = loader.load_terrain_csv(MAP_TERRAIN_DATA)

    def get_hex_center(self, col, row):
        """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
        x = HEX_RADIUS * math.sqrt(3) * (col + 0.5 * (row & 1))
        y = HEX_RADIUS * 3/2 * row
        return QPointF(x + X_OFFSET, y + Y_OFFSET)

    def get_vertex(self, center, i):
        """Calculate hex vertex position."""
        angle_rad = math.radians(60 * i - 30)
        return QPointF(center.x() + HEX_RADIUS * math.cos(angle_rad),
                       center.y() + HEX_RADIUS * math.sin(angle_rad))

    def get_neighbor_offset(self, col, row, direction_idx):
        """Calculate the neighbor hex coordinates based on direction."""
        parity = row & 1
        offsets = {
            0: [(1, 0), (1, 0)],
            1: [(0, 1), (1, 1)],
            2: [(-1, 1), (0, 1)],
            3: [(-1, 0), (-1, 0)],
            4: [(-1, -1), (0, -1)],
            5: [(0, -1), (1, -1)]
        }
        offset = offsets[direction_idx][parity]
        return col + offset[0], row + offset[1]


    def get_coastal_hexside_directions(self):
        """
        Returns a dict mapping (col, row) -> list of direction_indices for coastal hexes.
        For each sea hexside, colors wedges on BOTH the land hex and the adjacent ocean hex.
        """
        from collections import defaultdict
        coastal_dirs = defaultdict(list)

        sea_hexsides = self.map_cfg.hexsides.get("sea", [])
        dir_map = {"E": 0, "NE": 5, "NW": 4, "W": 3, "SW": 2, "SE": 1}
        opposite_dir = {0: 3, 1: 4, 2: 5, 3: 0, 4: 1, 5: 2}

        for col, row, direction in sea_hexsides:
            direction_idx = dir_map.get(direction)
            if direction_idx is not None:
                coastal_dirs[(col, row)].append(direction_idx)
                neighbor_col, neighbor_row = self.get_neighbor_offset(col, row, direction_idx)
                opposite_idx = opposite_dir[direction_idx]
                coastal_dirs[(neighbor_col, neighbor_row)].append(opposite_idx)

        return coastal_dirs

    def get_mountain_pass_directions(self):
        """
        Returns a dict mapping (col, row) -> list of direction_indices for mountain passes.
        Paints a line joining the centers of the adjacent hexes.
        """
        from collections import defaultdict
        pass_dirs = defaultdict(list)

        pass_hexsides = self.map_cfg.hexsides.get("pass", [])
        dir_map = {"E": 0, "NE": 5, "NW": 4, "W": 3, "SW": 2, "SE": 1}
        opposite_dir = {0: 3, 1: 4, 2: 5, 3: 0, 4: 1, 5: 2}

        for col, row, direction in pass_hexsides:
            direction_idx = dir_map.get(direction)
            if direction_idx is not None:
                pass_dirs[(col, row)].append(direction_idx)
                neighbor_col, neighbor_row = self.get_neighbor_offset(col, row, direction_idx)
                opposite_idx = opposite_dir[direction_idx]
                pass_dirs[(neighbor_col, neighbor_row)].append(opposite_idx)

        return pass_dirs

    def wheelEvent(self, event):
        """Zoom with Ctrl+Wheel."""
        if event.modifiers() == Qt.ControlModifier:
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
            self.scale(zoom_factor, zoom_factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def sync_with_model(self):
        """Redraws the map based on the current GameState model."""
        self.scene.clear()
        
        # Re-add background
        self.bg_item = self.scene.addPixmap(QPixmap(MAP_IMAGE_PATH))
        self.bg_item.setZValue(-1)

        # Get map bounds from scenario (if available)
        if self.game_state.map and hasattr(self.game_state.map, 'width'):
            map_width = self.game_state.map.width
            map_height = self.game_state.map.height
        else:
            # Default to full Ansalon map
            map_width = MAP_WIDTH
            map_height = MAP_HEIGHT

        # Build coastal information
        coastal_info = self.get_coastal_hexside_directions()

        # Draw all hexes with terrain
        for row in range(map_height):
            for col in range(map_width):
                center = self.get_hex_center(col, row)
                raw_terrain = self.terrain_data.get(f"{col},{row}", "ocean")
                
                # Extract coastal flag and terrain type
                is_coastal = raw_terrain.startswith("c_")
                t_type = raw_terrain[2:] if is_coastal else raw_terrain
                
                # Get coastal directions
                coastal_dirs = coastal_info.get((col, row))

                # Get mountain pass directions
                mountain_passes = self.get_mountain_pass_directions().get((col, row), [])
                
                # Draw base hex with transparent overlay
                hex_item = HexagonItem(center, HEX_RADIUS, QColor(0, 0, 0, 0),
                                      terrain_type=t_type, coastal_directions=coastal_dirs,
                                       pass_directions=mountain_passes
                                       )
                self.scene.addItem(hex_item)

        # Overlay country territories
        for cid, spec in self.country_specs.items():
            color = QColor(spec.color)
            rgba = QColor(color.red(), color.green(), color.blue(), 100)
            for col, row in spec.territories:
                center = self.get_hex_center(col, row)
                raw_terrain = self.terrain_data.get(f"{col},{row}", "grassland")
                is_coastal = raw_terrain.startswith("c_")
                t_type = raw_terrain[2:] if is_coastal else raw_terrain
                coastal_dirs = coastal_info.get((col, row))
                
                country_hex = HexagonItem(center, HEX_RADIUS, rgba,
                                         terrain_type=t_type, coastal_directions=coastal_dirs,
                                          pass_directions=mountain_passes
                                          )
                self.scene.addItem(country_hex)

        # Draw Hexsides (Rivers, Mountains, etc)
        hexsides = self.map_cfg.hexsides
        for side_type, entries in hexsides.items():
            if side_type in ["sea", "pass"]:  # Skip sea hexsides and mountain passes (already drawn as wedges or vectors)
                continue
            for col, row, direction in entries:
                center = self.get_hex_center(col, row)
                dir_map = {"E": 0, "NE": 5, "NW": 4, "W": 3, "SW": 2, "SE": 1}
                idx = dir_map.get(direction)
                
                if idx is not None:
                    p1 = self.get_vertex(center, idx)
                    p2 = self.get_vertex(center, (idx + 1) % 6)
                    self.scene.addItem(HexsideItem(p1, p2, side_type))

        # Draw locations
        self.draw_locations()

        # Draw units if map is initialized
        if self.game_state.map:
            for unit in self.game_state.units:
                if hasattr(unit, 'position') and unit.is_on_map:
                    col, row = unit.position
                    self.draw_unit(unit, col, row)

    def create_location_map(self):
        """Create location map, handling conflicts by preferring special locations."""
        location_map = {}

        # Add country locations first
        for country_spec in self.country_specs.values():
            for loc_spec in country_spec.locations:
                coords = loc_spec.coords
                if coords:
                    location_map[coords] = {
                        'type': loc_spec.loc_type,
                        'is_capital': loc_spec.is_capital,
                        'country_id': country_spec.id,
                        'location_id': loc_spec.id,
                    }

        # Add special locations
        for loc_spec in self.map_cfg.special_locations:
            coords = loc_spec.coords
            if coords:
                location_map[coords] = {
                    'type': loc_spec.loc_type,
                    'is_capital': False,
                    'country_id': None,
                    'location_id': loc_spec.id,
                }

        return location_map

    def draw_locations(self):
        """Draw location symbols."""
        for coords, loc in self.location_map.items():
            center = self.get_hex_center(coords[0], coords[1])
            loc_item = LocationItem(center, loc['location_id'], loc['type'], loc['is_capital'])
            self.scene.addItem(loc_item)

    def draw_unit(self, unit, col, row):
        """Helper to place a Unit graphics item on the map."""
        center = self.get_hex_center(col, row)
        unit_item = UnitGraphicsItem(unit, HEX_RADIUS)
        unit_item.setPos(center)
        unit_item.setZValue(10)  # Ensure units stay above hexes
        self.scene.addItem(unit_item)

    def highlight_movement_range(self, reachable_coords):
        """
        Loops through all HexagonItems in the scene and highlights them
        if their coordinates are in the reachable_coords list.
        """
        for item in self.scene.items():
            if isinstance(item, HexagonItem):
                # Extract col, row from center position
                # This is a reverse calculation - you may need to adjust
                is_reachable = False  # Implement coordinate matching
                item.set_highlight(is_reachable)
