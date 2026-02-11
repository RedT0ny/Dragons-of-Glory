import os
from time import perf_counter

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QTreeWidget, QTreeWidgetItem, QFrame, QPushButton, QLineEdit, QTextEdit,
                               QTreeWidgetItemIterator)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont, QPixmap

from src.content.specs import AssetType, UnitColumn
from src.gui.unit_panel import AllegiancePanel
from src.content.constants import WS, HL
from src.content.config import FONTS_DIR, LIBRA_FONT, IMAGES_DIR, DEBUG


class AssetDetails(QFrame):
    """Lower section of the Assets Tab showing details."""
    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.init_ui()
        self.current_asset = None
        self.current_unit = None

    def init_ui(self):
        layout = QHBoxLayout(self)

        # --- Left Column: Picture + Name ---
        left_container = QWidget()
        left_container.setFixedWidth(400)  # This forces the 400px width
        left_col = QVBoxLayout(left_container)  # Set the layout to the container

        left_col.addStretch()

        # Picture
        self.pic_label = QLabel()
        self.pic_label.setFixedSize(350, 350)
        self.pic_label.setAlignment(Qt.AlignCenter)  # Changed to Center for better looks
        self.pic_label.setStyleSheet("border: 2px dashed gray;")
        left_col.addWidget(self.pic_label, 0, Qt.AlignCenter)

        # Name
        self.name_label = QLabel("Select an asset")
        self.name_label.setAlignment(Qt.AlignCenter)

        # Set Font to Libra
        font_db = QFontDatabase()
        font_id = font_db.addApplicationFont(LIBRA_FONT)
        if font_id != -1:
            families = font_db.applicationFontFamilies(font_id)
            if families:
                self.name_label.setFont(QFont(families[0], 24))

        left_col.addWidget(self.name_label, 0, Qt.AlignCenter)
        left_col.addStretch()

        # Add the container widget to the main layout, not the layout itself
        layout.addWidget(left_container)

        # --- Right Column: Info + Desc + Buttons ---
        right_col = QVBoxLayout()

        self.bonus_field = QLineEdit()
        self.bonus_field.setReadOnly(True)
        self.bonus_field.setPlaceholderText("Asset Bonus")
        right_col.addWidget(self.bonus_field)

        # Description
        self.desc_field = QTextEdit()
        self.desc_field.setReadOnly(True)
        self.desc_field.setMaximumHeight(80)
        right_col.addWidget(self.desc_field)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_assign = QPushButton("Assign")
        self.btn_remove = QPushButton("Remove")
        self.btn_assign.setEnabled(False)
        self.btn_remove.setEnabled(False)

        btn_layout.addWidget(self.btn_assign)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        right_col.addLayout(btn_layout)

        layout.addLayout(right_col, 2)

    def display_asset(self, asset):
        self.current_asset = asset

        if not asset:
            self.name_label.setText("Select an asset")
            self.pic_label.clear()
            self.pic_label.setStyleSheet("border: 2px dashed gray;")
            self.bonus_field.clear()
            self.desc_field.clear()
            return

        self.name_label.setText(asset.spec.id.replace("_", " ").title())
        self.desc_field.setText(asset.description)

        # Bonus Text
        if isinstance(asset.bonus, dict):
            bonus_str = ", ".join([f"{k}: {v}" for k,v in asset.bonus.items()])
        else:
            bonus_str = str(asset.bonus)
        self.bonus_field.setText(bonus_str)

        # Picture Border Color
        border_color = "gold" # Default Artifact
        if asset.asset_type == AssetType.RESOURCE:
            border_color = "silver"
        elif asset.asset_type == AssetType.BANNER:
            border_color = "peru"

        self.pic_label.setStyleSheet(f"border: 10px solid {border_color};")

        # Load Picture
        img_name = asset.spec.picture if hasattr(asset.spec, 'picture') and asset.spec.picture else "artifact.jpg"
        img_path = os.path.join(IMAGES_DIR, img_name)
        if not os.path.exists(img_path):
            img_path = os.path.join(IMAGES_DIR, "artifact.jpg")
        if os.path.exists(img_path):
            self.pic_label.setPixmap(QPixmap(img_path).scaled(350, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.pic_label.setText("Img not found")


    def update_buttons_state(self, unit):
        """Logic to enable/disable buttons based on selection."""
        self.current_unit = unit
        asset = self.current_asset

        # Reset
        self.btn_assign.setEnabled(False)
        self.btn_remove.setEnabled(False)

        if not asset:
            return

        # Case: Asset is not equippable
        if not asset.is_equippable:
            return

        # Case: Unit with artifact is selected (Removal logic)
        if unit and hasattr(unit, 'equipment') and unit.equipment:
            # If the displayed asset IS the one on the unit, enable remove
            if asset in unit.equipment:
                self.btn_remove.setEnabled(True)
            return

        # Case: Asset selected, Empty Unit selected (Assign logic)
        if unit and (not hasattr(unit, 'equipment') or not unit.equipment):
            # Only if asset is currently free (not assigned to someone else)
            if asset.assigned_to is None:
                self.btn_assign.setEnabled(True)

class AssetsTab(QWidget):
    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self._last_signature = None
        self.unit_panel = None
        self.unit_panel_allegiance = None
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Upper Section (Split 2/3 and 1/3) ---
        upper_widget = QWidget()
        upper_layout = QHBoxLayout(upper_widget)

        # 1. Unit Panel (Left - 2/3) - Now using AllegiancePanel
        # We need a placeholder that we refresh
        self.panel_container = QWidget()
        self.panel_layout = QVBoxLayout(self.panel_container)
        self.panel_layout.setContentsMargins(0,0,0,0)
        
        upper_layout.addWidget(self.panel_container, stretch=2)

        # 2. Asset Tree (Right - 1/3)
        self.asset_tree = QTreeWidget()
        self.asset_tree.setHeaderLabel("Player Assets")
        upper_layout.addWidget(self.asset_tree, stretch=1)

        main_layout.addWidget(upper_widget, stretch=1)

        # --- Lower Section ---
        self.details_panel = AssetDetails()
        self.details_panel.btn_assign.clicked.connect(self.on_assign_clicked)
        self.details_panel.btn_remove.clicked.connect(self.on_remove_clicked)
        main_layout.addWidget(self.details_panel, stretch=1)

        # Signals
        self.asset_tree.itemSelectionChanged.connect(self.on_tree_asset_selected)
        
        self.current_selected_unit = None

    def _build_signature(self):
        if not self.game_state or not self.game_state.current_player:
            return None
        player = self.game_state.current_player

        units = []
        for u in self.game_state.units:
            if u.allegiance != player.allegiance:
                continue
            equip = tuple(sorted(getattr(a.spec, "id", str(a)) for a in getattr(u, "equipment", []) or []))
            units.append((
                str(getattr(u, "id", "")),
                int(getattr(u, "ordinal", 0) or 0),
                str(getattr(getattr(u, "status", None), "name", getattr(u, "status", ""))),
                tuple(getattr(u, "position", (None, None)) or (None, None)),
                int(getattr(u, "movement_points", getattr(u, "movement", 0)) or 0),
                bool(getattr(u, "attacked_this_turn", False)),
                equip,
            ))
        units.sort()

        assets = []
        for aid, asset in sorted(player.assets.items(), key=lambda kv: kv[0]):
            assigned = getattr(asset, "assigned_to", None)
            if assigned is None:
                assigned_key = None
            else:
                assigned_key = (
                    str(getattr(assigned, "id", "")),
                    int(getattr(assigned, "ordinal", 0) or 0),
                )
            assets.append((
                str(aid),
                str(getattr(getattr(asset, "asset_type", None), "value", getattr(asset, "asset_type", ""))),
                assigned_key,
            ))

        return (player.allegiance, tuple(units), tuple(assets))

    def refresh(self):
        """Reloads data from GameState."""
        t0 = perf_counter()
        if not self.game_state or not self.game_state.current_player:
            return

        signature = self._build_signature()
        if signature == self._last_signature:
            if DEBUG:
                print("[perf] AssetsTab.refresh skipped (signature unchanged)")
            return
        self._last_signature = signature

        player = self.game_state.current_player

        # 1. Refresh Unit Panel
        if self.unit_panel is None or self.unit_panel_allegiance != player.allegiance:
            while self.panel_layout.count():
                item = self.panel_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            columns = [
                UnitColumn.ICON,
                UnitColumn.NAME,
                UnitColumn.TYPE,
                UnitColumn.POS,
                UnitColumn.EQUIPMENT
            ]
            self.unit_panel = AllegiancePanel(self.game_state, player.allegiance, columns, title="Player Units")
            self.unit_panel.unit_selected.connect(self.on_unit_selected)
            self.panel_layout.addWidget(self.unit_panel)
            self.unit_panel_allegiance = player.allegiance
        else:
            self.unit_panel.refresh()

        # 2. Refresh Asset Tree
        self.asset_tree.blockSignals(True)
        self.asset_tree.clear()

        cats = {
            AssetType.ARTIFACT: QTreeWidgetItem(["Artifacts"]),
            AssetType.RESOURCE: QTreeWidgetItem(["Resources"]),
            AssetType.BANNER: QTreeWidgetItem(["Banners"])
        }
        for c in cats.values():
            self.asset_tree.addTopLevelItem(c)

        for asset_id, asset in player.assets.items():
            node = QTreeWidgetItem([asset.spec.id.replace("_", " ").title()])
            node.setData(0, Qt.UserRole, asset) # Store asset object

            # Add to category
            if asset.asset_type in cats:
                cats[asset.asset_type].addChild(node)
            else:
                cats[AssetType.ARTIFACT].addChild(node) # Fallback

        self.asset_tree.expandAll()
        self.asset_tree.blockSignals(False)
        dt_ms = (perf_counter() - t0) * 1000.0
        if DEBUG:
            print(f"[perf] AssetsTab.refresh rebuilt assets={len(player.assets)} time_ms={dt_ms:.1f}")

    def select_asset_by_id(self, asset_id):
        """Selects an asset in the tree by its ID."""
        if not asset_id:
            return

        iterator = QTreeWidgetItemIterator(self.asset_tree)
        while iterator.value():
            item = iterator.value()
            asset = item.data(0, Qt.UserRole)
            if asset and asset.id == asset_id:
                self.asset_tree.setCurrentItem(item)
                self.on_tree_asset_selected() # Manually trigger update
                break
            iterator += 1

    def on_unit_selected(self, unit):
        self.current_selected_unit = unit
        
        if not unit:
            self.details_panel.update_buttons_state(None)
            return

        # Logic: If unit has artifact, select it in details
        asset_to_show = None
        if hasattr(unit, 'equipment') and unit.equipment:
            asset_to_show = unit.equipment[0] # Show first

            # Deselect tree
            self.asset_tree.blockSignals(True)
            self.asset_tree.clearSelection()
            self.asset_tree.blockSignals(False)

        # If unit has NO artifact, we keep the tree selection if exists
        elif self.asset_tree.selectedItems():
            item = self.asset_tree.selectedItems()[0]
            asset_to_show = item.data(0, Qt.UserRole)

        self.details_panel.display_asset(asset_to_show)
        self.details_panel.update_buttons_state(unit)

    def on_tree_asset_selected(self):
        selected = self.asset_tree.selectedItems()
        if not selected:
            return

        item = selected[0]
        asset = item.data(0, Qt.UserRole)
        if not asset: return # Category label

        self.details_panel.display_asset(asset)
        self.details_panel.update_buttons_state(self.current_selected_unit)

    def on_assign_clicked(self):
        unit = self.details_panel.current_unit
        asset = self.details_panel.current_asset
        if unit and asset:
            asset.apply_to(unit)
            self.refresh() # Update table
            # Reselect logic? Complex because widgets recreated. 
            # We lose selection when refreshing completely.
            # Ideally we should keep state or partial refresh, but full refresh is robust.
            # We reset selection.
            self.details_panel.update_buttons_state(None)

    def on_remove_clicked(self):
        unit = self.details_panel.current_unit
        asset = self.details_panel.current_asset
        if unit and asset:
            asset.remove_from(unit)
            self.refresh()
            self.details_panel.update_buttons_state(None)
