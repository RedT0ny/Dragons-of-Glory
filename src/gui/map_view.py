import math

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QMessageBox
from PySide6.QtGui import QPainter, QColor, QPixmap, QBrush, QMouseEvent
from PySide6.QtCore import Qt, QPointF

from src.content.constants import WS
from src.content.specs import UnitState, GamePhase
from src.content.config import (DEBUG, HEX_RADIUS, MAP_IMAGE_PATH, COUNTRIES_DATA, MAP_CONFIG_DATA, MAP_TERRAIN_DATA,
                                MAP_WIDTH, MAP_HEIGHT, X_OFFSET, Y_OFFSET)
from src.content import loader
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

        # Load map data
        self.load_all_data()

    def load_all_data(self):
        """Load all map configuration data."""
        self.country_specs = loader.load_countries_yaml(COUNTRIES_DATA)
        self.map_cfg = loader.load_map_config(MAP_CONFIG_DATA)
        self.location_map = self.create_location_map()
        self.terrain_data = loader.load_terrain_csv(MAP_TERRAIN_DATA)

        # Create country color lookup: {"country_id": QColor}
        self.country_colors = {
            spec.id: QColor(spec.color)
            for spec in self.country_specs.values()
        }

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

        if target_hex:
            # Convert scene pos back to hex coords?
            # Or assume we stored valid coords.
            # For now, let's assume we can map back or stored the hex item mapping.
            # Simplified: Just place it (Logic would go to Controller ideally)

            # Update Unit State
            self.deploying_unit.status = UnitState.ACTIVE

            # Reverse engineer coords from center (approximate)
            # Or better, store coords in HexagonItem
            # For this snippet, assuming we have a way to set position:
            # self.game_state.move_unit(self.deploying_unit, hex_coords)

            self.deploying_unit = None
            self.clear_highlights()
            self.sync_with_model()

            # Show dialog again? Or let user maximize it.

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
                # Trigger Merge Dialog
                self.show_merge_dialog(units[0], units[1])
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
        for item in self.scene.items():
            if isinstance(item, HexagonItem):
                item.set_highlight(False)

    def draw_static_map(self):
        """Draws the static elements of the map (terrain, borders, locations)."""
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

        # Build mountain pass information
        mountain_passes_map = self.get_mountain_pass_directions()

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
                mountain_passes = mountain_passes_map.get((col, row), [])

                # Draw base hex with transparent overlay
                hex_item = HexagonItem(center, HEX_RADIUS, QColor(0, 0, 0, 0),
                                       terrain_type=t_type, coastal_directions=coastal_dirs,
                                       pass_directions=mountain_passes
                                       )
                self.scene.addItem(hex_item)

        # Overlay country territories
        for cid, spec in self.country_specs.items():
            if not self.should_draw_country(cid):
                continue

            color = QColor(spec.color)
            rgba = QColor(color.red(), color.green(), color.blue(), 100)
            for col, row in spec.territories:
                center = self.get_hex_center(col, row)
                raw_terrain = self.terrain_data.get(f"{col},{row}", "grassland")
                is_coastal = raw_terrain.startswith("c_")
                t_type = raw_terrain[2:] if is_coastal else raw_terrain
                coastal_dirs = coastal_info.get((col, row))
                mountain_passes = mountain_passes_map.get((col, row), [])

                country_hex = HexagonItem(center, HEX_RADIUS, rgba,
                                          terrain_type=t_type, coastal_directions=coastal_dirs,
                                          pass_directions=mountain_passes,
                                          country_id=cid
                                          )
                self.scene.addItem(country_hex)

        # Draw Hexsides (Rivers, Mountains, etc)
        hexsides = self.map_cfg.hexsides
        for side_type, entries in hexsides.items():
            if side_type in ["sea", "pass"]:  # Skip sea hexsides and mountain passes
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

        # Get the color for this unit's country (fallback to allegiance colors if no country)
        color = self.country_colors.get(unit.land,
                                        QColor("blue") if unit.allegiance == WS else QColor("red"))

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
                # Extract col, row from center position
                # This is a reverse calculation - you may need to adjust
                is_reachable = False  # Implement coordinate matching
                item.set_highlight(is_reachable)
