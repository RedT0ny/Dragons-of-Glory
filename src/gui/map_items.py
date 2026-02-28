import math, os

from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsItem
from PySide6.QtGui import QPainter, QPainterPath, QColor, QBrush, QPen
from PySide6.QtCore import Qt, QPointF, QRectF, QByteArray

from src.content.constants import WS, TERRAIN_VISUALS, HEXSIDE_COLORS, UI_COLORS, EVIL_DRAGONFLIGHTS
from src.content.specs import UnitType, UnitRace, UnitState
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

    def shape(self):
        # Use the real hex polygon for scene hit-testing instead of the bounding rectangle.
        return self.path

    def contains(self, point):
        return self.path.contains(point)

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
    _renderer_light = None

    @classmethod
    def get_shared_renderer(cls):
        if cls._renderer is None:
            cls._renderer = QSvgRenderer(os.path.join(ICONS_DIR, "units.svg"))
        return cls._renderer

    @classmethod
    def get_light_renderer(cls):
        if cls._renderer_light is not None:
            return cls._renderer_light
        try:
            with open(os.path.join(ICONS_DIR, "units.svg"), "r", encoding="utf-8") as f:
                svg_text = f.read()
            light_text = svg_text.replace("#000000", "#ffffff").replace("#000", "#fff")
            cls._renderer_light = QSvgRenderer(QByteArray(light_text.encode("utf-8")))
        except Exception:
            cls._renderer_light = cls.get_shared_renderer()
        return cls._renderer_light

    def __init__(self, unit, color, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.color = color
        size = UNIT_SIZE
        self.unit_rect = QRectF(-size, -size, size*2, size*2)
        self.renderer = self.get_shared_renderer()
        try:
            self._element_id = self._get_element_id() or "noicon"
        except Exception:
            self._element_id = "noicon"

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

    def _get_icon_renderer(self):
        element_id = self._element_id or "noicon"
        if self._is_precolored_group(element_id):
            return self.renderer
        allegiance = getattr(self.unit, "allegiance", WS)
        if allegiance == WS:
            return self.get_light_renderer()
        return self.renderer

    def _draw_icon(self, painter):
        element_id = self._element_id or "noicon"
        renderer = self._get_icon_renderer()
        if not renderer.elementExists(element_id):
            element_id = "noicon"
        if not renderer.elementExists(element_id):
            return
        target_size = max(14, int(round(UNIT_SIZE * 0.9)))
        bounds = renderer.boundsOnElement(element_id)
        if bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
            bounds = QRectF(0, 0, 1, 1)

        aspect = bounds.width() / bounds.height() if bounds.height() else 1.0
        if aspect >= 1.0:
            draw_w = target_size
            draw_h = max(1.0, target_size / aspect)
        else:
            draw_h = target_size
            draw_w = max(1.0, target_size * aspect)

        x = self.unit_rect.center().x() - (draw_w / 2.0)
        y = self.unit_rect.center().y() - (draw_h / 2.0)
        renderer.render(painter, element_id, QRectF(x, y, draw_w, draw_h))

    def boundingRect(self):
        padding = 4
        return self.unit_rect.adjusted(-padding, -padding, padding, padding)

    def paint(self, painter, option, widget):
        # Background
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(self.color))
        painter.setPen(QPen(QColor(255, 255, 255) if getattr(self.unit, 'allegiance', None) == WS else QColor(0, 0, 0), 2))
        painter.drawRoundedRect(self.unit_rect, 5, 5)
        self._draw_icon(painter)

        # ID
        id_color, rating_color, move_color, movement_display = self._get_text_colors_and_movement()

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
        self._draw_badges(painter)

    def _get_text_colors_and_movement(self):
        base_text_color = QColor(255, 255, 255) if getattr(self.unit, 'allegiance', None) == WS else QColor(0, 0, 0)
        gray_text_color = QColor(160, 160, 160)

        max_movement = getattr(self.unit, "movement", 0)
        remaining_movement = getattr(self.unit, "movement_points", max_movement)
        remaining_movement = max(0, remaining_movement)

        attacked = bool(getattr(self.unit, "attacked_this_turn", False))
        depleted = bool(getattr(self.unit, "status", None) == UnitState.DEPLETED)

        if attacked:
            id_color = gray_text_color
            rating_color = gray_text_color
            move_color = gray_text_color
            movement_display = remaining_movement
            return id_color, rating_color, move_color, movement_display

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

        if depleted:
            rating_color = gray_text_color

        return id_color, rating_color, move_color, movement_display

    def _draw_badges(self, painter):
        # Passenger badge (carriers)
        try:
            passengers = getattr(self.unit, 'passengers', None) or []
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
                bx = self.unit_rect.right() - br * 2 - 2
                by = self.unit_rect.center().y() - br
                badge_rect = QRectF(bx, by, br * 2, br * 2)
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
            pass
