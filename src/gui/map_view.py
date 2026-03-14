import math

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QMessageBox
from PySide6.QtGui import QPainter, QColor, QPixmap, QBrush, QMouseEvent
from PySide6.QtCore import Qt, QPointF, QTimer, Signal
import shiboken6

from src.content.constants import WS, HL, UI_COLORS
from src.content.runtime_diagnostics import RuntimeDiagnostics
from src.content.specs import UnitState, GamePhase, UnitType
from src.content.config import (DEBUG, HEX_RADIUS, MAP_IMAGE_PATH,
                                MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET, OVERLAY_ALPHA)
from src.game.map import Hex
from src.gui.map_items import HexagonItem, HexsideItem, LocationItem, UnitCounter, HexOverlayItem

class AnsalonMapView(QGraphicsView):
    # Added Signals to notify main window
    units_clicked = Signal(list)
    hex_clicked = Signal(object)
    right_clicked = Signal()
    hex_hovered = Signal(str, int, int, str, str)
    unit_deployment_requested = Signal(object, object)  # unit, target_hex
    unit_movement_requested = Signal(object, object)    # unit, target_hex
    depleted_merge_requested = Signal(object, object)   # unit1, unit2

    def __init__(self, game_state, parent=None, overlay_alpha=50):
        super().__init__(parent)
        self.game_state = game_state
        self.overlay_alpha = overlay_alpha
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        #self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setMouseTracking(True) # Enable hover tracking

        # Edge scrolling
        self.edge_scroll_timer = QTimer(self)
        self.edge_scroll_timer.timeout.connect(self.handle_edge_scrolling)
        self.edge_scroll_active = False
        self.edge_scroll_direction = (0, 0)

        # Deployment state
        self.deploying_unit = None

        # Optimization: Track unit items to remove them individually
        self.unit_items = []
        self.hex_items = []
        self.hex_items_by_coords = {}
        self.overlay_items = []
        self.overlay_items_by_coords = {}
        self.map_rendered = False
        self.initial_fit_done = False
        self.zoom_on_show = 1.0
        self._sync_in_progress = False
        self._sync_pending = False
        self.overlay_mode = "political"

    def showEvent(self, event):
        """Fit the map to the view when shown for the first time."""
        super().showEvent(event)
        if not self.initial_fit_done:
            # Use a single shot timer to let the layout settle before fitting
            QTimer.singleShot(0, self._perform_initial_zoom)

    def _perform_initial_zoom(self):
        """ Fits map to view on first show event."""
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

    def handle_edge_scrolling(self):
        """Handle automatic scrolling when mouse is near screen edges."""
        if self.edge_scroll_active:
            dx, dy = self.edge_scroll_direction
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    def wheelEvent(self, event):
        """Zoom with Ctrl+Wheel."""
        if self._sync_in_progress:
            event.accept()
            return
        if event.modifiers() & Qt.ControlModifier:
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
            current_zoom = self.transform().m11()
            min_zoom = 0.20
            max_zoom = 6.0
            proposed_zoom = current_zoom * zoom_factor
            if min_zoom <= proposed_zoom <= max_zoom:
                self.scale(zoom_factor, zoom_factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle hover events to update info panel."""
        super().mouseMoveEvent(event)

        scene_pos = self.mapToScene(event.position().toPoint())
        items = self.scene.items(scene_pos)

        # Find HexagonItem under cursor
        hex_item = None
        for item in items:
            if isinstance(item, HexagonItem):
                hex_item = item
                break

        if hex_item and hasattr(hex_item, 'coords'):
            col, row = hex_item.coords

            # Fetch data from GameState
            from src.game.map import Hex
            hex_obj = Hex.offset_to_axial(col, row)

            if self.game_state and self.game_state.map:
                terrain = self.game_state.map.get_terrain(hex_obj)
                loc_obj = self.game_state.map.get_location(hex_obj)

                loc_name = "-"
                occupier_name = "-"
                if loc_obj:
                    loc_name = getattr(loc_obj, 'id', 'Unknown')
                    loc_name = str(loc_name).replace("_", " ").title()

                overlay = None
                if self.game_state:
                    overlay = self.game_state.get_overlay("territory")
                    if overlay is None:
                        overlay = self.game_state.get_overlay("control")

                allegiance = None
                if overlay and overlay.values:
                    allegiance = overlay.values.get((col, row))

                if allegiance == HL:
                    occupier_name = "Highlord"
                elif allegiance == WS:
                    occupier_name = "Whitestone"
                elif allegiance == "contested":
                    occupier_name = "Contested"
                elif loc_obj:
                    occupier = getattr(loc_obj, "occupier", None)
                    if occupier:
                        occupier_name = str(occupier).replace("_", " ").title()

                terrain_str = terrain.value.title() if terrain else "Unknown"
                self.hex_hovered.emit(terrain_str, col, row, loc_name, occupier_name)

    def mousePressEvent(self, event: QMouseEvent):
        """Handle clicks for deployment or depleted unit interaction."""
        current_player = getattr(self.game_state, "current_player", None)
        is_human = bool(current_player and not getattr(current_player, "is_ai", False))
        interactive_phase = self.game_state.phase in {
            GamePhase.DEPLOYMENT,
            GamePhase.REPLACEMENTS,
            GamePhase.MOVEMENT,
            GamePhase.COMBAT,
        }
        deployment_active = self.deploying_unit is not None
        deployment_session_active = False
        try:
            win = self.window()
            controller = getattr(win, "controller", None)
            if controller and hasattr(controller, "_is_deployment_session_active"):
                deployment_session_active = bool(controller._is_deployment_session_active())
        except Exception:
            deployment_session_active = False
        if not is_human and not deployment_session_active:
            super().mousePressEvent(event)
            return
        if not interactive_phase and not deployment_active and not deployment_session_active:
            # Ignore map clicks outside normal human-interactive phases,
            # except when an explicit deployment selection is active
            # (e.g. strategic event/activation triggered deployments).
            super().mousePressEvent(event)
            return

        # Scenario 1: Right-click Deselect
        if event.button() == Qt.RightButton:
            self.right_clicked.emit()
            return

        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())

        # Global Unit Selection Logic
        # Detect clicks on units to populate Info Panel
        items = self.scene.items(scene_pos)
        clicked_units = []
        for item in items:
            if isinstance(item, UnitCounter):
                clicked_units.append(item.unit)

        if clicked_units:
            # Sort clicked units if needed, or pass as is (stack logic usually draws top last)
            # The top unit in visual stack is the first in hit test usually?
            # items() returns top-most first.
            self.units_clicked.emit(clicked_units)

        # 1. Handle Deployment from Replacement Dialog
        if self.deploying_unit:
            self.handle_deployment_click(scene_pos)
            return

        # 2. Handle Movement Phase Clicks
        if self.game_state.phase == GamePhase.MOVEMENT:
            if self.handle_movement_click(scene_pos):
                return

        # 3. Handle Combat Phase Clicks
        if self.game_state.phase == GamePhase.COMBAT:
            # Combat clicks need to detect hexes even if NOT highlighted (to select stacks)
            # handle_movement_click only works on highlighted items.
            if self.handle_combat_click_view(scene_pos):
                return

        # 4. Handle Depleted Unit Stacking (only in Replacements Phase)
        if self.game_state.phase == GamePhase.REPLACEMENTS:
            self.handle_depleted_stack_click(scene_pos)
            return

        super().mousePressEvent(event)

    def handle_movement_click(self, scene_pos):
        items = self.scene.items(scene_pos)
        for item in items:
            if isinstance(item, HexagonItem) and item.is_highlighted:
                from src.game.map import Hex
                col, row = item.coords
                hex_obj = Hex.offset_to_axial(col, row)
                # Defer to avoid scene mutation re-entrancy during mouse event dispatch.
                QTimer.singleShot(0, lambda h=hex_obj: self.hex_clicked.emit(h))
                return True
        return False

    def handle_combat_click_view(self, scene_pos):
        """Detects click on ANY hex during combat to allow stack selection."""
        items = self.scene.items(scene_pos)
        for item in items:
            if isinstance(item, HexagonItem):
                # We accept any hex click here, the Controller decides if it's valid
                # (Friend to select, Enemy to target, Empty to deselect)
                from src.game.map import Hex
                col, row = item.coords
                hex_obj = Hex.offset_to_axial(col, row)
                # Defer to avoid scene mutation re-entrancy during mouse event dispatch.
                QTimer.singleShot(0, lambda h=hex_obj: self.hex_clicked.emit(h))
                return True
        return False


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
            # Emit signal instead of directly calling game state
            from src.game.map import Hex
            col, row = target_hex.coords
            hex_obj = Hex.offset_to_axial(col, row)

            # Defer to avoid scene mutation re-entrancy during mouse event dispatch.
            unit = self.deploying_unit
            QTimer.singleShot(0, lambda u=unit, h=hex_obj: self.unit_deployment_requested.emit(u, h))

            # Clear UI state (cursor, highlights)
            self.deploying_unit = None
            self.clear_highlights()

            # Note: Let controller handle unit state updates and model sync

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

        # Filter for Depleted + Active Player + eligible conscription types.
        candidates = [u for u in clicked_units
                      if u.status == UnitState.DEPLETED
                      and u.allegiance == self.game_state.active_player
                      and (u.is_fleet() or u.is_army())]

        # Group by replacement rule key (army country/dragonflight or fleet country).
        from collections import defaultdict
        by_group = defaultdict(list)
        for u in candidates:
            by_group[self.game_state.get_replacement_group_key(u)].append(u)

        for _, units in by_group.items():
            if len(units) >= 2:
                # Defer signal to avoid scene mutation during event processing.
                u1, u2 = units[0], units[1]
                QTimer.singleShot(0, lambda a=u1, b=u2: self.depleted_merge_requested.emit(a, b))
                break # Handle one pair at a time

    def highlight_deployment_targets(self, valid_coords_list, unit):
        """Highlights hexes where the 'ready' unit can be placed."""
        self.clear_highlights()
        self.deploying_unit = unit

        # Change cursor to indicate placement mode (overrides ScrollHandDrag)
        self.setCursor(Qt.PointingHandCursor)

        # Highlight all valid coordinates using indexed hex items.
        # This avoids repeated scene spatial queries during rapid UI interaction.
        for col, row in valid_coords_list:
            for item in self.hex_items_by_coords.get((col, row), []):
                if shiboken6.isValid(item):
                    item.set_highlight(True)

    def clear_highlights(self):
        self.deploying_unit = None

        # Restore default cursor (returns to ScrollHandDrag "open hand")
        self.unsetCursor()

        for item in self.hex_items:
            if shiboken6.isValid(item) and item.is_highlighted:
                item.set_highlight(False)

    def draw_static_map(self):
        """Draws the static elements of the map based on GameState model."""
        self.hex_items = []
        self.hex_items_by_coords = {}
        self.overlay_items = []
        self.overlay_items_by_coords = {}
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
                    if idx in [0, 1, 2] and hexside and hexside in ["river", "deep_river", "mountain"]:
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
                self.hex_items.append(hex_item)
                self.hex_items_by_coords.setdefault((col, row), []).append(hex_item)

                overlay_item = HexOverlayItem(center, HEX_RADIUS, QColor(0, 0, 0, 0))
                overlay_item.coords = (col, row)
                overlay_item.setZValue(1)
                self.scene.addItem(overlay_item)
                self.overlay_items.append(overlay_item)
                self.overlay_items_by_coords[(col, row)] = overlay_item

                # 5. Draw Location if present
                # loc_data = board.get_location(hex_obj)
                # if loc_data:
                #     loc_item = LocationItem(center, loc_data['location_id'],
                #                              loc_data['type'], loc_data['is_capital'])
                #     self.scene.addItem(loc_item)

        self.refresh_overlay()

    def sync_with_model(self):
        """Redraws the map based on the current GameState model."""
        if self._sync_in_progress:
            self._sync_pending = True
            RuntimeDiagnostics.record_event("Map sync skipped: sync already in progress")
            return

        self._sync_in_progress = True
        try:
            RuntimeDiagnostics.record_event("Map sync start")
            self._sync_pending = False
            if not self.map_rendered:
                self.scene.clear()
                self.draw_static_map()
                self.map_rendered = True

            # Clean up old unit items
            for item in self.unit_items:
                if shiboken6.isValid(item) and item.scene() == self.scene:
                    self.scene.removeItem(item)
            self.unit_items.clear()

            # Draw units if map is initialized
            if self.game_state.map:
                # Group units by position to handle stacking
                units_by_hex = {} # (col, row) -> [unit, unit...]

                for unit in self.game_state.units:
                    # Skip transported units (they are represented on the carrier)
                    if getattr(unit, 'transport_host', None):
                        continue
                    if hasattr(unit, 'position') and unit.is_on_map:
                        pos = unit.position # (col, row)
                        if pos not in units_by_hex:
                            units_by_hex[pos] = []
                        units_by_hex[pos].append(unit)

                # Draw each stack
                for pos, stack in units_by_hex.items():
                    self.draw_stack(stack, pos[0], pos[1])
            self.refresh_overlay()
            RuntimeDiagnostics.record_event("Map sync end")
        finally:
            self._sync_in_progress = False
            if self._sync_pending:
                QTimer.singleShot(0, self.sync_with_model)

    def reset_view_for_new_map(self):
        """
        Hard reset scene/render caches after loading a save, so static map and unit items
        are rebuilt against the new model state.
        """
        self.deploying_unit = None
        self._sync_pending = False
        self._sync_in_progress = False
        self.unit_items.clear()
        self.hex_items.clear()
        self.hex_items_by_coords.clear()
        self.overlay_items.clear()
        self.overlay_items_by_coords.clear()
        self.scene.clear()
        self.map_rendered = False

    def draw_stack(self, stack, col, row):
        """Draws a list of units at a specific hex with visual stacking offset."""
        base_center = self.get_hex_center(col, row)

        # Sort stack for consistent rendering (e.g., Army bottom, Leader top)
        # Order: Fleet -> Army -> Wing -> Leader/Hero/Wizard
        def sort_key(u):
            order = {'fleet': 0, 'inf': 1, 'cav': 1, 'wing': 2, 'dragon': 2}
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

    def highlight_movement_range(self, reachable_coords, warning_coords=None):
        """
        Loops through all HexagonItems in the scene and highlights them
        if their coordinates are in the reachable_coords list.
        reachable_coords: List of (col, row) tuples.
        """
        reachable_set = set(reachable_coords)
        warning_set = set(warning_coords or [])
        # Highlights reachable hexagons by comparing item coordinates
        for item in self.scene.items():
            if isinstance(item, HexagonItem):
                if item.coords in warning_set:
                    item.set_highlight(True, UI_COLORS["neutral_warning_hex"])
                elif item.coords in reachable_set:
                    if not item.is_highlighted or item.highlight_color is not None:
                        item.set_highlight(True)
                else:
                    if item.is_highlighted:
                        item.set_highlight(False)

    def set_overlay(self, mode: str):
        self.overlay_mode = mode or "political"
        self.refresh_overlay()

    def refresh_overlay(self):
        if not self.game_state or not getattr(self.game_state, "map", None):
            return
        overlay = self.game_state.get_overlay(self.overlay_mode)
        if overlay is None:
            for item in self.overlay_items:
                if shiboken6.isValid(item):
                    item.set_color(QColor(0, 0, 0, 0))
            return

        values = overlay.values or {}
        for (col, row), item in self.overlay_items_by_coords.items():
            if not shiboken6.isValid(item):
                continue
            value = values.get((col, row))
            if overlay.kind == "country":
                item.country_id = value
            else:
                item.country_id = None
            color = self._overlay_color_for_value(overlay, value)
            item.set_color(color)

    def _overlay_color_for_value(self, overlay, value):
        if value is None:
            return QColor(0, 0, 0, 0)
        kind = overlay.kind
        if kind == "country":
            country = self.game_state.countries.get(value)
            if not country:
                return QColor(0, 0, 0, 0)
            if not self.should_draw_country(country.id):
                return QColor(0, 0, 0, 0)
            c = QColor(country.color)
            return QColor(c.red(), c.green(), c.blue(), self.overlay_alpha)
        if kind == "allegiance":
            if value == WS:
                return QColor(0, 0, 255, self.overlay_alpha)
            if value == HL:
                return QColor(255, 0, 0, self.overlay_alpha)
            if value == "contested":
                return QColor(128, 0, 128, self.overlay_alpha)
            return QColor(0, 0, 0, 0)

        if kind == "scalar":
            max_val = float(overlay.max_value or 0.0)
            if max_val <= 0:
                return QColor(0, 0, 0, 0)
            intensity = min(1.0, max(0.0, float(value) / max_val))
            if self.overlay_mode == "supply":
                return QColor(0, 128, 0, int(self.overlay_alpha * intensity))
            if self.overlay_mode == "ws_power":
                return QColor(0, 0, 255, int(self.overlay_alpha * intensity))
            if self.overlay_mode == "hl_power":
                return QColor(255, 0, 0, int(self.overlay_alpha * intensity))
            if self.overlay_mode == "threat":
                if intensity <= 0.1:
                    return QColor(0, 120, 0, int(self.overlay_alpha))
                if intensity <= 0.25:
                    return QColor(120, 180, 0, int(self.overlay_alpha))
                if intensity <= 0.45:
                    return QColor(220, 200, 0, int(self.overlay_alpha))
                if intensity <= 0.65:
                    return QColor(255, 140, 0, int(self.overlay_alpha))
                if intensity <= 0.85:
                    return QColor(200, 0, 0, int(self.overlay_alpha))
                return QColor(80, 0, 0, self.overlay_alpha)
            return QColor(0, 0, 0, 0)

        return QColor(0, 0, 0, 0)
