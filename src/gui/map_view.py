import math

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QMessageBox
from PySide6.QtGui import QPainter, QColor, QPixmap, QBrush, QMouseEvent
from PySide6.QtCore import Qt, QPointF, QTimer

from src.content.constants import WS
from src.content.specs import UnitState, GamePhase
from src.content.config import (DEBUG, HEX_RADIUS, MAP_IMAGE_PATH,
                                MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET)
from src.game.map import Hex
from src.gui.map_items import HexagonItem, HexsideItem, LocationItem, UnitCounter

class AnsalonMapView(QGraphicsView):
    def __init__(self, game_state, parent=None):
        super().__init__(parent)
        self.game_state = game_state
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        # Deployment state
        self.deploying_unit = None

        # Optimization: Track unit items to remove them individually
        self.unit_items = []
        self.map_rendered = False
        self.initial_fit_done = False

    def showEvent(self, event):
        """Fit the map to the view when shown for the first time."""
        super().showEvent(event)
        if not self.initial_fit_done and self.scene.itemsBoundingRect().width() > 0:
            self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
            self.initial_fit_done = True

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

    def should_draw_country(self, country_id):
        """Hook to filter which countries are drawn. By default, draw all."""
        return True

    def wheelEvent(self, event):
        """Zoom with Ctrl+Wheel."""
        if event.modifiers() == Qt.ControlModifier:
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
            self.scale(zoom_factor, zoom_factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """Handle clicks for deployment or depleted unit interaction."""
        super().mousePressEvent(event)

        if event.button() != Qt.LeftButton:
            return

        scene_pos = self.mapToScene(event.position().toPoint())

        # 1. Handle Deployment from Replacement Dialog
        if self.deploying_unit:
            self.handle_deployment_click(scene_pos)
            return

        # 2. Handle Depleted Unit Stacking (only in Replacements Phase)
        if self.game_state.phase == GamePhase.REPLACEMENTS:
            self.handle_depleted_stack_click(scene_pos)

    def handle_deployment_click(self, scene_pos):
        # Find hex at this position
        # Simple proximity check or utilizing QGraphicsItem detection
        items = self.scene.items(scene_pos)
        target_hex = None
        for item in items:
            if isinstance(item, HexagonItem) and item.is_highlighted:
                target_hex = item
                break

        if target_hex and hasattr(target_hex, 'coords'):
            # Execute Move
            from src.game.map import Hex
            col, row = target_hex.coords
            hex_obj = Hex.offset_to_axial(col, row)

            self.game_state.move_unit(self.deploying_unit, hex_obj)

            # Update Unit State
            self.deploying_unit.status = UnitState.ACTIVE

            self.deploying_unit = None
            self.clear_highlights()
            self.sync_with_model()

            # Ideally signal the dialog to refresh, but for now user can maximize it manually

    def handle_depleted_stack_click(self, scene_pos):
        # Find units at this location
        # This requires spatial query
        # Simplified:
        items = self.scene.items(scene_pos)
        clicked_units = []
        for item in items:
            if isinstance(item, UnitCounter):
                clicked_units.append(item.unit)

        if not clicked_units:
            return

        # Filter for Depleted + Same Nationality + Active Player
        candidates = [u for u in clicked_units
                      if u.status == UnitState.DEPLETED
                      and u.allegiance == self.game_state.active_player]

        # Group by country
        from collections import defaultdict
        by_country = defaultdict(list)
        for u in candidates:
            by_country[u.land].append(u)

        for country, units in by_country.items():
            if len(units) >= 2:
                # Trigger Merge Dialog deferred to avoid scene clearing during event processing
                QTimer.singleShot(0, lambda: self.show_merge_dialog(units[0], units[1]))
                break # Handle one pair at a time

    def show_merge_dialog(self, unit1, unit2):
        from src.gui.replacements_dialog import UnitSelectionDialog
        dlg = UnitSelectionDialog(unit1, unit2, self)
        dlg.setWindowTitle("Reinforce Unit")
        if dlg.exec():
            # Selected becomes ACTIVE (Full)
            dlg.selected_unit.status = UnitState.ACTIVE

            # Discarded goes to RESERVE (Pool)
            dlg.discarded_unit.status = UnitState.RESERVE
            dlg.discarded_unit.position = (None, None) # Remove from map

            self.sync_with_model()

    def highlight_deployment_targets(self, valid_coords_list, unit):
        """Highlights hexes where the 'ready' unit can be placed."""
        self.clear_highlights()
        self.deploying_unit = unit

        # Change cursor to indicate placement mode (overrides ScrollHandDrag)
        self.setCursor(Qt.PointingHandCursor)

        # This requires HexagonItem to store its coords or a lookup
        # For this implementation, we iterate scene items (inefficient but works for small map)
        # or use get_hex_center if we have coords.

        for col, row in valid_coords_list:
            center = self.get_hex_center(col, row)
            # Find item at center
            items = self.scene.items(center)
            for item in items:
                if isinstance(item, HexagonItem):
                    item.set_highlight(True)
                    break

    def clear_highlights(self):
        self.deploying_unit = None

        # Restore default cursor (returns to ScrollHandDrag "open hand")
        self.unsetCursor()

        for item in self.scene.items():
            if isinstance(item, HexagonItem):
                item.set_highlight(False)

    def draw_static_map(self):
        """Draws the static elements of the map based on GameState model."""
        self.bg_item = self.scene.addPixmap(QPixmap(MAP_IMAGE_PATH))
        self.bg_item.setZValue(-1)

        board = self.game_state.map
        if not board:
            return # Should not happen if initialized correctly

        map_width = board.width
        map_height = board.height

        # Draw all hexes
        for row in range(map_height):
            for col in range(map_width):
                hex_obj = Hex.offset_to_axial(col, row)
                center = self.get_hex_center(col, row)

                # 1. Terrain info from Board
                t_type = board.get_terrain(hex_obj)
                is_coastal = board.is_coastal(hex_obj)

                # 2. Coastal Directions (Dynamic check)
                coastal_dirs = []
                # 3. Mountain Passes (Dynamic check)
                pass_directions = []

                neighbors = hex_obj.neighbors() # Returns [E, SE, SW, W, NW, NE] -> indices 0..5

                for idx, neighbor in enumerate(neighbors):
                    hexside = board.get_hexside(hex_obj, neighbor)

                    if hexside == "sea":
                        coastal_dirs.append(idx)
                    elif hexside == "pass":
                        pass_directions.append(idx)

                    # 4. Draw Hexside Items (Rivers, etc)
                    # To avoid duplicates, we only draw for specific directions (e.g. E, SE, SW)
                    if idx in [0, 1, 2] and hexside and hexside not in ["sea", "pass"]:
                        # Calculate vertices for this edge
                        # Edge i connects vertex i and (i+1)%6
                        p1 = self.get_vertex(center, idx)
                        p2 = self.get_vertex(center, (idx + 1) % 6)
                        self.scene.addItem(HexsideItem(p1, p2, hexside))

                # Draw Base Hex
                hex_item = HexagonItem(center, HEX_RADIUS, QColor(0, 0, 0, 0),
                                       terrain_type=t_type, coastal_directions=coastal_dirs,
                                       pass_directions=pass_directions)
                hex_item.coords = (col, row)
                self.scene.addItem(hex_item)

                # 5. Draw Location if present
                loc_data = board.get_location(hex_obj)
                if loc_data:
                    loc_item = LocationItem(center, loc_data['location_id'],
                                            loc_data['type'], loc_data['is_capital'])
                    self.scene.addItem(loc_item)

        # Overlay Country territories
        # Iterate GameState countries directly
        for country in self.game_state.countries.values():
            if not self.should_draw_country(country.id):
                continue

            # Use country.color from Spec/YAML
            c_color = QColor(country.color)
            rgba = QColor(c_color.red(), c_color.green(), c_color.blue(), 100)

            for col, row in country.territories:
                hex_obj = Hex.offset_to_axial(col, row)
                center = self.get_hex_center(col, row)

                # Re-query terrain for overlay
                t_type = board.get_terrain(hex_obj)

                # Re-calc coastal/pass for overlay
                c_dirs = []
                p_dirs = []
                neighbors = hex_obj.neighbors()
                for idx, neighbor in enumerate(neighbors):
                    hexside = board.get_hexside(hex_obj, neighbor)
                    if hexside == "sea": c_dirs.append(idx)
                    if hexside == "pass": p_dirs.append(idx)

                country_hex = HexagonItem(center, HEX_RADIUS, rgba,
                                          terrain_type=t_type, coastal_directions=c_dirs,
                                          pass_directions=p_dirs,
                                          country_id=country.id)
                country_hex.coords = (col, row)  # Fix: Ensure overlay hexes also have coords
                self.scene.addItem(country_hex)

    def sync_with_model(self):
        """Redraws the map based on the current GameState model."""
        if not self.map_rendered:
            self.scene.clear()
            self.draw_static_map()
            self.map_rendered = True

        # Clean up old unit items
        for item in self.unit_items:
            if item.scene() == self.scene:
                self.scene.removeItem(item)
        self.unit_items.clear()

        # Draw units if map is initialized
        if self.game_state.map:
            for unit in self.game_state.units:
                if hasattr(unit, 'position') and unit.is_on_map:
                    col, row = unit.position
                    self.draw_unit(unit, col, row)

    def draw_unit(self, unit, col, row):
        """Helper to place a Unit graphics item on the map."""
        center = self.get_hex_center(col, row)

        # Get color logic - simplified
        if unit.land and unit.land in self.game_state.countries:
            c_spec = self.game_state.countries[unit.land]
            color = QColor(c_spec.color)
        else:
            color = QColor("blue") if unit.allegiance == WS else QColor("red")

        unit_item = UnitCounter(unit, color)
        unit_item.setPos(center)
        unit_item.setZValue(10)  # Ensure units stay above hexes
        self.scene.addItem(unit_item)
        self.unit_items.append(unit_item)

    def highlight_movement_range(self, reachable_coords):
        """
        Loops through all HexagonItems in the scene and highlights them
        if their coordinates are in the reachable_coords list.
        """
        for item in self.scene.items():
            if isinstance(item, HexagonItem):
                item.set_highlight(False) # Reset first
                # TODO: Implement actual reachability highlight
