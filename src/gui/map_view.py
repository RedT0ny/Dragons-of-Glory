import math

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QMessageBox
from PySide6.QtGui import QPainter, QColor, QPixmap, QBrush, QMouseEvent
from PySide6.QtCore import Qt, QPointF, QTimer

from src.content.constants import WS
from src.content.specs import UnitState, GamePhase
from src.content.config import (DEBUG, HEX_RADIUS, MAP_IMAGE_PATH,
                                MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET, OVERLAY_ALPHA)
from src.game.map import Hex
from src.gui.map_items import HexagonItem, HexsideItem, LocationItem, UnitCounter

class AnsalonMapView(QGraphicsView):
    def __init__(self, game_state, parent=None):
        super().__init__(parent)
        self.game_state = game_state
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        #self.setDragMode(QGraphicsView.ScrollHandDrag)

        # Deployment state
        self.deploying_unit = None

        # Optimization: Track unit items to remove them individually
        self.unit_items = []
        self.map_rendered = False
        self.initial_fit_done = False
        self.zoom_on_show = 1.0

    def showEvent(self, event):
        """Fit the map to the view when shown for the first time."""
        super().showEvent(event)
        if not self.initial_fit_done and self.scene.itemsBoundingRect().width() > 0:
            self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
            if self.zoom_on_show != 1.0:
                self.scale(self.zoom_on_show, self.zoom_on_show)
            self.initial_fit_done = True

    def get_hex_center(self, col, row):
        """Calculates pixel center for a pointy-top hex using odd-r offset coordinates."""
        offset_col = getattr(self.game_state.map, "offset_col", 0) if self.game_state.map else 0
        offset_row = getattr(self.game_state.map, "offset_row", 0) if self.game_state.map else 0
        draw_col = col + offset_col
        draw_row = row + offset_row

        x = HEX_RADIUS * math.sqrt(3) * (draw_col + 0.5 * (draw_row & 1))
        y = HEX_RADIUS * 3/2 * draw_row
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
            # NEW: Check stacking limits before highlighting!
            from src.game.map import Hex
            hex_obj = Hex.offset_to_axial(col, row)

            # Highlights valid hexes where unit can move
            if self.game_state.map.can_unit_move_to(unit, hex_obj):
                center = self.get_hex_center(col, row)
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
            # Iterates hex grid; draws terrain, hexsides, and locations
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
            rgba = QColor(c_color.red(), c_color.green(), c_color.blue(), OVERLAY_ALPHA)

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
            # Group units by position to handle stacking
            units_by_hex = {} # (col, row) -> [unit, unit...]

            for unit in self.game_state.units:
                if hasattr(unit, 'position') and unit.is_on_map:
                    pos = unit.position # (col, row)
                    if pos not in units_by_hex:
                        units_by_hex[pos] = []
                    units_by_hex[pos].append(unit)

            # Draw each stack
            for pos, stack in units_by_hex.items():
                self.draw_stack(stack, pos[0], pos[1])

    def draw_stack(self, stack, col, row):
        """Draws a list of units at a specific hex with visual stacking offset."""
        base_center = self.get_hex_center(col, row)

        # Sort stack for consistent rendering (e.g., Army bottom, Leader top)
        # Order: Fleet -> Wing -> Army -> Leader/Hero/Wizard
        def sort_key(u):
            order = {'fleet': 0, 'wing': 1, 'inf': 2, 'cav': 2, 'dragon': 1}
            return order.get(u.unit_type, 3) # Default to 3 (top)

        stack.sort(key=sort_key)

        # Stacking visual parameters
        max_offset_items = 5 # Stop offsetting after the 5th unit to prevent spillover
        offset_x = -5 # Shift slightly left
        offset_y = -5 # Shift slightly up (to look like a pile)

        for i, unit in enumerate(stack):
            # Calculate offset
            # If we exceed the limit, we just pile them on top of the last offset position
            # so the user sees "there are more" but it stays in hex.
            idx = min(i, max_offset_items - 1)

            # We start from bottom-right and move to top-left to simulate 3D piling
            # Or simply offset center.
            # Let's do a simple diagonal shift.

            # To center the *pile*, we might want the first unit to be slightly bottom-right
            # relative to the hex center.

            dx = idx * offset_x
            dy = idx * offset_y

            # Center the whole stack visually?
            # Let's anchor the bottom unit at (center + slight positive offset)
            # so the top unit ends up near (center + slight negative offset)
            start_x = base_center.x() - (dx / 2) # Crude centering adjustment
            start_y = base_center.y() - (dy / 2)

            pos = QPointF(start_x + dx, start_y + dy)

            # Draw the unit
            self.draw_unit_at_pos(unit, pos)

    def draw_unit_at_pos(self, unit, pos):
        """Helper to place a Unit graphics item at a specific pixel position."""
        # Get color logic - simplified
        if unit.land and unit.land in self.game_state.countries:
            c_spec = self.game_state.countries[unit.land]
            color = QColor(c_spec.color)
        else:
            color = QColor("blue") if unit.allegiance == WS else QColor("red")

        unit_item = UnitCounter(unit, color)
        unit_item.setPos(pos)
        unit_item.setZValue(10 + self.unit_items.count(unit_item)) # Ensure correct Z-order in stack
        self.scene.addItem(unit_item)
        self.unit_items.append(unit_item)

    # Removed the old draw_unit method as it is replaced by draw_stack logic

    def highlight_movement_range(self, reachable_coords):
        """
        Loops through all HexagonItems in the scene and highlights them
        if their coordinates are in the reachable_coords list.
        """
        for item in self.scene.items():
            if isinstance(item, HexagonItem):
                item.set_highlight(False) # Reset first
                # TODO: Implement actual reachability highlight
