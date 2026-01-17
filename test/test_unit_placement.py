from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QVBoxLayout, QGraphicsView, QGraphicsItem, QGraphicsColorizeEffect
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QBrush, QPen, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import Qt, QPointF, QTimer, QRectF
from test.test_window import *
from src.content import loader, factory, config
from src.content.config import COUNTRIES_DATA, MAP_IMAGE_PATH, X_OFFSET, Y_OFFSET, SCENARIOS_DIR, ICONS_DIR, \
    UNIT_SIZE
from src.content.constants import HL, WS, EVIL_DRAGONFLIGHTS
from src.content.specs import UnitType, UnitRace

SCENARIO = os.path.join(SCENARIOS_DIR, "scenario_2_solamnic_plain.yaml")

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
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)

        id_text = f"{self.unit.id}"
        painter.drawText(self.unit_rect, Qt.AlignHCenter | Qt.AlignTop, id_text)

        # Draw stats at bottom
        # Choose combat or tactical rating
        rating = self.unit.combat_rating if self.unit.combat_rating != 0 else self.unit.tactical_rating
        stats_text = f"{rating}      {self.unit.movement}"
        painter.drawText(self.unit_rect, Qt.AlignHCenter | Qt.AlignBottom, stats_text)

        # DEBUG: Draw bounding rect
        if config.DEBUG:
            painter.setPen(Qt.red)
            painter.drawRect(self.boundingRect())

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

    def load_data(self):

        # 1. Load Countries
        self.country_specs = loader.load_countries_yaml(COUNTRIES_DATA)
        self.scenario_spec = loader.load_scenario_yaml(SCENARIO)

        # The factory does all the heavy lifting
        scenario_obj = factory.create_scenario(self.scenario_spec)

        self.units = scenario_obj.units
        self.countries = scenario_obj.countries

        # Create country color lookup: {"country_id": QColor}
        self.country_colors = {
            spec.id: QColor(spec.color)
            for spec in self.country_specs.values()
        }

    def load_map_image(self):
        """Load the full resolution map background image."""

        if os.path.exists(MAP_IMAGE_PATH):
            self.map_pixmap = QPixmap(MAP_IMAGE_PATH)
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

    def get_hex_center(self, col, row):
        """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
        x = HEX_RADIUS * math.sqrt(3) * (col + 0.5 * (row & 1))
        y = HEX_RADIUS * 3/2 * row
        return QPointF(x + X_OFFSET, y + Y_OFFSET)

    def draw_hex_grid(self):
        """Draw the hexagonal grid overlay."""
        # Draw empty hexes first (background grid)
        for row in range(MAP_HEIGHT):
            for col in range(MAP_WIDTH):
                center = self.get_hex_center(col, row)
                hex_item = HexagonItem(center, HEX_RADIUS, (200, 200, 200, 30))
                self.scene.addItem(hex_item)

    def draw_unit(self, unit, col, row):
        """Helper to place a Unit graphics item on the map."""
        center = self.get_hex_center(col, row)

        # Get the color for this unit's country (fallback to allegiance colors if no country)
        color = self.country_colors.get(unit.land,
                                        QColor("blue") if unit.allegiance == WS else QColor("red"))

        unit_item = UnitCounter(unit, color)
        unit_item.setPos(center)
        unit_item.setZValue(10)  # Ensure units stay above hexes
        self.scene.addItem(unit_item)


    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)

    def draw_content(self):
        """Draw hex grid and units in the center of the map."""
        col = 25
        row = 25
        max_col = 31
        self.draw_hex_grid()
        for unit in self.units:
            self.draw_unit(unit, col, row)
            col += 1
            if col >= max_col:
                col = 25
                row += 1

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.viewer = MapViewer()
    layout = QVBoxLayout()
    layout.addWidget(window.viewer)
    window.setLayout(layout)

    QTimer.singleShot(100, window.viewer.draw_content)

    window.show()
    sys.exit(app.exec())


