import math, os

from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsItem, QGraphicsColorizeEffect
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen
from PySide6.QtCore import Qt, QPointF, QRectF

from src.content.constants import WS, TERRAIN_VISUALS, HEXSIDE_COLORS, UI_COLORS, EVIL_DRAGONFLIGHTS, HL
from src.content.specs import UnitType, UnitRace
from src.content.utils import caption_id
from src.content.config import (DEBUG, LOCATION_SIZE, ICONS_DIR, UNIT_SIZE)


class HexagonItem(QGraphicsItem):
    def __init__(self, center, radius, color, terrain_type="grassland", coastal_directions=None, pass_directions=None, parent=None, country_id=None):
        super().__init__(parent)
        self.center = center
        self.radius = radius
        # Ensure color is a QColor object even if a tuple is passed
        # Handle None case by defaulting to transparent
        if color is None:
            self.color = QColor(0, 0, 0, 0)  # Transparent black
        elif isinstance(color, (tuple, list)):
            self.color = QColor(*color)
        else:
            self.color = color
        self.terrain_type = terrain_type
        self.coastal_directions = coastal_directions or []
        self.pass_directions = pass_directions or []
        self.is_highlighted = False # Track if this hex is a valid move
        self.points = []
        self.country_id = country_id
    
        # Create pointy-top hexagon path
        self.path = QPainterPath()
        # Creates hexagon vertices using polar coordinates
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
        if self.color and self.color.alpha() > 0:
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
            painter.setBrush(QBrush(UI_COLORS["highlighted_hex"]))
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


class UnitCounter(QGraphicsItem):
    """Visual representation of a Unit from the model."""

    def __init__(self, unit, color, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.color = color
        size = UNIT_SIZE
        self.unit_rect = QRectF(-size, -size, size*2, size*2)
        # Single SVG file containing both symbols and groups
        self.renderer = QSvgRenderer(os.path.join(ICONS_DIR, "units.svg"))

        # Create icon ONCE, not in paint()
        self.icon = self.create_unit_icon()
        if self.icon:
            self.icon.setParentItem(self)
            # Center the icon
            self.center_icon()

    def center_icon(self):
        """Center the icon within unit_rect."""
        """Scale icon to appropriate size and center it."""
        if not self.icon:
            return

        # Get icon's natural size
        icon_rect = self.icon.boundingRect()

        # Target size: 60-80% of unit size
        target_size = UNIT_SIZE * 0.9

        # Calculate scale (maintain aspect ratio)
        scale_x = target_size / icon_rect.width()
        scale_y = target_size / icon_rect.height()
        scale = min(scale_x, scale_y)

        # Apply scale transform
        self.icon.setScale(scale)

        # Recalculate bounds after scaling
        icon_rect = self.icon.sceneBoundingRect()

        # Center in unit_rect
        self.icon.setPos(self.unit_rect.center() - icon_rect.center())

    def paint(self, painter, option, widget):
        # Draw background rectangle
        painter.setBrush(QBrush(self.color))
        painter.setPen(QPen(Qt.white if self.unit.allegiance == WS else Qt.black, 2))
        painter.drawRoundedRect(self.unit_rect, 5, 5)

        # Draw unit ID at top
        painter.setPen(Qt.white if self.unit.allegiance == WS else Qt.black)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)

        id_text = caption_id(self.unit.id)
        painter.drawText(self.unit_rect, Qt.AlignHCenter | Qt.AlignTop, id_text)

        # Draw stats at bottom
        # Choose combat or tactical rating
        rating = self.unit.combat_rating if self.unit.combat_rating != 0 else self.unit.tactical_rating
        stats_text = f"{rating}      {self.unit.movement}"
        painter.drawText(self.unit_rect, Qt.AlignHCenter | Qt.AlignBottom, stats_text)

    def boundingRect(self):
        """Return bounding rectangle for the unit with padding."""
        padding = 4  # For selection, hover effects
        return self.unit_rect.adjusted(-padding, -padding, padding, padding)

    def create_unit_icon(self):
        # Determine which SVG element to use
        element_id = self._get_element_id()

        # Create the SVG item
        icon = QGraphicsSvgItem()
        icon.setSharedRenderer(self.renderer)
        try:
            icon.setElementId(element_id)
        except:
            print(f"SVG element '{element_id}' not found, using fallback")
            icon.setElementId("noicon")

        # Apply coloring
        if not self._is_precolored_group(element_id):
            self._apply_allegiance_colors(icon)

        return icon

    def _get_element_id(self):
        """Determine which SVG element to reference."""
        if self.unit.unit_type in [UnitType.WIZARD, UnitType.HIGHLORD,
                                   UnitType.EMPEROR, UnitType.CITADEL,
                                   UnitType.FLEET, UnitType.CAVALRY]:
            return self.unit.unit_type.value
        elif self.unit.unit_type in [UnitType.ADMIRAL, UnitType.GENERAL, UnitType.HERO]:
            if self.unit.race == UnitRace.SOLAMNIC:
                return "knight"
            if self.unit.id in ["soth", "laurana"]:
                return self.unit.id
            elif self.unit.race == UnitRace.ELF:
                return "elflord"
            else:
                return "leader"
        elif self.unit.race == UnitRace.DRAGON:
            if self.unit.land in EVIL_DRAGONFLIGHTS:
                return "evil_dragon"
            else:
                return "good_dragon"
        elif self.unit.race in [UnitRace.HUMAN, UnitRace.SOLAMNIC]:
            return self.unit.unit_type.value  # FIXED
        return self.unit.race.value

    def _is_precolored_group(self, element_id):
        """Check if this is a fixed-color group, like lord Soth, undead or locations"""
        return element_id.startswith('full-') or element_id.startswith('loc-')

    def _apply_allegiance_colors(self, icon):
        """Simple colorization based on allegiance."""
        allegiance = getattr(self.unit, 'allegiance', WS)

        effect = QGraphicsColorizeEffect()

        if allegiance == HL:
            effect.setColor(Qt.black)
        elif allegiance == WS:
            effect.setColor(Qt.white)
        else:  # NEUTRAL
            effect.setColor(Qt.gray)  # Gray

        icon.setGraphicsEffect(effect)
