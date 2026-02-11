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
        self.highlight_color = None
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

    def set_highlight(self, highlight: bool, color=None):
        self.is_highlighted = highlight
        self.highlight_color = color if highlight else None
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
            highlight_color = self.highlight_color or UI_COLORS["highlighted_hex"]
            painter.setBrush(QBrush(highlight_color))
            pen_color = QColor(200, 0, 0) if self.highlight_color else QColor(255, 255, 0)
            painter.setPen(QPen(pen_color, 2))
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
    """Clean UnitCounter that renders unit icon, id, stats and transport badges.

    Badges implemented:
    - Carrier (has .passengers): gold circular badge on the right edge with passenger count
    - Transported unit (.is_transported): small rounded rect at top-right with carrier.ordinal
    """
    _renderer = None

    @classmethod
    def get_shared_renderer(cls):
        if cls._renderer is None:
            cls._renderer = QSvgRenderer(os.path.join(ICONS_DIR, "units.svg"))
        return cls._renderer

    def __init__(self, unit, color, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.color = color
        size = UNIT_SIZE
        self.unit_rect = QRectF(-size, -size, size*2, size*2)
        self.renderer = self.get_shared_renderer()

        # Create and attach icon
        self.icon = self.create_unit_icon()
        if self.icon:
            self.icon.setParentItem(self)
            self.center_icon()

    def center_icon(self):
        if not self.icon:
            return
        icon_rect = self.icon.boundingRect()
        target = UNIT_SIZE * 0.9
        sx = target / icon_rect.width() if icon_rect.width() else 1.0
        sy = target / icon_rect.height() if icon_rect.height() else 1.0
        s = min(sx, sy)
        self.icon.setScale(s)
        # center
        icon_rect = self.icon.sceneBoundingRect()
        self.icon.setPos(self.unit_rect.center() - icon_rect.center())

    def create_unit_icon(self):
        item = QGraphicsSvgItem()
        item.setSharedRenderer(self.renderer)
        # Determine element id once and reuse; be defensive to avoid raising inside paint
        try:
            element_id = self._get_element_id()
        except Exception:
            element_id = None

        try:
            if element_id:
                item.setElementId(element_id)
            else:
                item.setElementId("noicon")
        except Exception:
            try:
                item.setElementId("noicon")
            except Exception:
                pass

        try:
            if element_id and not self._is_precolored_group(element_id):
                self._apply_allegiance_colors(item)
        except Exception:
            # Don't let coloring failures crash paint
            pass
        return item

    def _get_element_id(self):
        # Be defensive: unit_type and race may be None during some flows (tests/mocks)
        utype = getattr(self.unit, 'unit_type', None)
        urace = getattr(self.unit, 'race', None)
        uid = getattr(self.unit, 'id', None)

        if utype in [UnitType.WIZARD, UnitType.HIGHLORD,
                     UnitType.EMPEROR, UnitType.CITADEL,
                     UnitType.FLEET, UnitType.CAVALRY]:
            return self.unit.unit_type.value
        if utype in [UnitType.ADMIRAL, UnitType.GENERAL, UnitType.HERO]:
            if urace == UnitRace.SOLAMNIC:
                return "knight"
            if uid in ["soth", "laurana"]:
                return uid
            if urace == UnitRace.ELF:
                return "elflord"
            return "leader"
        if urace == UnitRace.DRAGON:
            land = getattr(self.unit, 'land', None)
            return "evil_dragon" if land in EVIL_DRAGONFLIGHTS else "good_dragon"
        if urace in [UnitRace.HUMAN, UnitRace.SOLAMNIC] and utype:
            return utype.value
        # Fallback: safe string or noicon
        try:
            if urace is not None:
                return str(urace.value)
        except Exception:
            pass
        return "noicon"

    def _is_precolored_group(self, element_id):
        return isinstance(element_id, str) and (element_id.startswith('full-') or element_id.startswith('loc-'))

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

    def boundingRect(self):
        padding = 4
        return self.unit_rect.adjusted(-padding, -padding, padding, padding)

    def paint(self, painter, option, widget):
        # Background
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(self.color))
        painter.setPen(QPen(QColor(255, 255, 255) if getattr(self.unit, 'allegiance', None) == WS else QColor(0, 0, 0), 2))
        painter.drawRoundedRect(self.unit_rect, 5, 5)

        # ID
        base_text_color = QColor(255, 255, 255) if getattr(self.unit, 'allegiance', None) == WS else QColor(0, 0, 0)
        gray_text_color = QColor(160, 160, 160)
        max_movement = getattr(self.unit, "movement", 0)
        remaining_movement = getattr(self.unit, "movement_points", max_movement)
        remaining_movement = max(0, remaining_movement)

        if remaining_movement == 0:
            id_color = gray_text_color
            rating_color = gray_text_color
            move_color = gray_text_color
            movement_display = 0
        elif remaining_movement < max_movement:
            id_color = base_text_color
            rating_color = base_text_color
            move_color = gray_text_color
            movement_display = remaining_movement
        else:
            id_color = base_text_color
            rating_color = base_text_color
            move_color = base_text_color
            movement_display = max_movement

        painter.setPen(QPen(id_color))
        f = painter.font()
        f.setPointSize(8)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(self.unit_rect, Qt.AlignHCenter | Qt.AlignTop, caption_id(self.unit.id))

        # Stats
        rating = self.unit.combat_rating if getattr(self.unit, 'combat_rating', 0) != 0 else getattr(self.unit, 'tactical_rating', 0)
        stats_rect = self.unit_rect.adjusted(4, 0, -4, -2)
        left_rect = QRectF(stats_rect.left(), stats_rect.top(), stats_rect.width() / 2, stats_rect.height())
        right_rect = QRectF(stats_rect.center().x(), stats_rect.top(), stats_rect.width() / 2, stats_rect.height())

        painter.setPen(QPen(rating_color))
        painter.drawText(left_rect, Qt.AlignHCenter | Qt.AlignBottom, str(rating))
        painter.setPen(QPen(move_color))
        painter.drawText(right_rect, Qt.AlignHCenter | Qt.AlignBottom, str(movement_display))

        # Passenger badge (carriers)
        try:
            passengers = getattr(self.unit, 'passengers', None) or []
            # Normalize passenger count safely
            pax_count = 0
            if hasattr(passengers, '__len__'):
                try:
                    pax_count = len(passengers)
                except Exception:
                    try:
                        pax_count = sum(1 for _ in passengers)
                    except Exception:
                        pax_count = 0

            if pax_count > 0:
                badge_text = str(pax_count)
                br = 10
                bx = self.unit_rect.right() - br*2 - 2
                by = self.unit_rect.center().y() - br
                badge_rect = QRectF(bx, by, br*2, br*2)
                painter.setBrush(QBrush(QColor(255, 215, 0)))  # gold
                painter.setPen(QPen(QColor(0, 0, 0), 1))
                painter.drawEllipse(badge_rect)
                pf = painter.font()
                pf.setPointSize(8)
                pf.setBold(True)
                painter.setFont(pf)
                painter.setPen(QPen(QColor(0, 0, 0)))
                painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
        except Exception:
            # Painting must not raise; swallow to avoid crashing the Qt paint loop
            pass

        # Transported badge (armies aboard a carrier)
        try:
            is_transported = bool(getattr(self.unit, 'is_transported', False))
            host = getattr(self.unit, 'transport_host', None)
            if is_transported and host is not None:
                host_num = getattr(host, 'ordinal', None)
                if host_num is None:
                    host_num = getattr(host, 'ordinal_index', None)
                if host_num is None:
                    host_num = getattr(host, 'id', None)

                if host_num is not None:
                    host_text = str(host_num)
                    tw, th = 18, 14
                    tx = self.unit_rect.right() - tw - 2
                    ty = self.unit_rect.top() + 2
                    trect = QRectF(tx, ty, tw, th)
                    painter.setBrush(QBrush(QColor(200, 200, 200)))
                    painter.setPen(QPen(QColor(0, 0, 0), 1))
                    painter.drawRoundedRect(trect, 3, 3)
                    pf2 = painter.font()
                    pf2.setPointSize(8)
                    pf2.setBold(True)
                    painter.setFont(pf2)
                    painter.setPen(QPen(QColor(0, 0, 0)))
                    painter.drawText(trect, Qt.AlignCenter, host_text)
        except Exception:
            # Protect paint from exceptions
            pass
