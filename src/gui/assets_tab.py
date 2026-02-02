from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QTreeWidget, QTreeWidgetItem, QFrame, QPushButton, QLineEdit, QTextEdit)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont, QPixmap

from src.content.specs import AssetType, UnitColumn
from src.gui.unit_panel import AllegiancePanel
from src.content.constants import WS
from src.content.config import FONTS_DIR, LIBRA_FONT


class AssetDetails(QFrame):
    """Lower section of the Assets Tab showing details."""
    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.init_ui()
        self.current_asset = None
        self.current_unit = None

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Top: Picture + Info
        top_row = QHBoxLayout()

        # Picture
        self.pic_label = QLabel()
        self.pic_label.setFixedSize(150, 150)
        self.pic_label.setAlignment(Qt.AlignCenter)
        self.pic_label.setStyleSheet("border: 2px dashed gray;")
        top_row.addWidget(self.pic_label)

        # Info (Name + Bonus)
        info_col = QVBoxLayout()

        self.name_label = QLabel("Select an asset")
        # Set Font to Libra
        font_db = QFontDatabase()
        font_id = font_db.addApplicationFont(LIBRA_FONT)
        if font_id != -1:
            families = font_db.applicationFontFamilies(font_id)
            if families:
                self.name_label.setFont(QFont(families[0], 24))

        info_col.addWidget(self.name_label)

        self.bonus_field = QLineEdit()
        self.bonus_field.setReadOnly(True)
        self.bonus_field.setPlaceholderText("Asset Bonus")
        info_col.addWidget(self.bonus_field)

        top_row.addLayout(info_col)
        layout.addLayout(top_row)

        # Description
        self.desc_field = QTextEdit()
        self.desc_field.setReadOnly(True)
        self.desc_field.setMaximumHeight(80)
        layout.addWidget(self.desc_field)

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
        layout.addLayout(btn_layout)

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
        border_color = "black" # Default Artifact
        if asset.asset_type == AssetType.RESOURCE:
            border_color = "silver"
        elif asset.asset_type == AssetType.BANNER:
            border_color = "green"

        self.pic_label.setStyleSheet(f"border: 4px solid {border_color};")

        # Load Picture
        pix = QPixmap(f"assets/img/{asset.spec.picture}")
        if not pix.isNull():
            self.pic_label.setPixmap(pix.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.pic_label.setText("No Image")

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
        main_layout.addWidget(self.details_panel, stretch=0)

        # Signals
        self.asset_tree.itemSelectionChanged.connect(self.on_tree_asset_selected)
        
        self.current_selected_unit = None

    def refresh(self):
        """Reloads data from GameState."""
        if not self.game_state or not self.game_state.current_player:
            return

        player = self.game_state.current_player

        # 1. Refresh Unit Panel
        while self.panel_layout.count():
             item = self.panel_layout.takeAt(0)
             if item.widget():
                 item.widget().deleteLater()

        # Use columns: Icon, Name, Type, Equipment
        columns = [
            UnitColumn.ICON,
            UnitColumn.NAME,
            UnitColumn.TYPE,
            UnitColumn.EQUIPMENT
        ]
        self.unit_panel = AllegiancePanel(self.game_state, player.allegiance, columns, title="Player Units")
        self.unit_panel.unit_selected.connect(self.on_unit_selected)

        self.panel_layout.addWidget(self.unit_panel)

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
