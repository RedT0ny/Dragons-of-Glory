from collections import deque
import os
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.content.config import ICONS_DIR
from src.content.specs import UnitColumn, UnitState
from src.content.tools import TextFormatter
from src.gui.message_dialog import MessageDialog
from src.gui.unit_panel import UnitTable

_PENDING_COMBAT_DIALOGS = deque()
_COMBAT_DIALOG_ACTIVE = False

def _is_verbose(game_state) -> bool:
    return str(getattr(game_state, "combat_details", "brief")).strip().lower() == "verbose"

def _to_offset_coords(target_hex) -> Optional[Tuple[int, int]]:
    if target_hex is None:
        return None
    if hasattr(target_hex, "axial_to_offset"):
        try:
            return target_hex.axial_to_offset()
        except Exception:
            return None
    if isinstance(target_hex, (tuple, list)) and len(target_hex) == 2:
        try:
            return int(target_hex[0]), int(target_hex[1])
        except Exception:
            return None
    return None

def _build_combat_body_widget(
    combat_type: str,
    target_hex_str: str,
    attackers: list,
    defenders: list,
    leader_escape_requests: list,
    advance_available: bool,
    game_state=None,
) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    tables_row = QHBoxLayout()
    tables_row.setSpacing(12)

    attacker_allegiance = attackers[0].allegiance if attackers else ""
    atk_group = QGroupBox(f"Attacker ({attacker_allegiance})")
    atk_table = UnitTable([UnitColumn.ICON, UnitColumn.NAME, UnitColumn.STATUS])
    atk_table.set_units(attackers, game_state)
    atk_group_layout = QVBoxLayout(atk_group)
    atk_group_layout.setContentsMargins(4, 4, 4, 4)
    atk_group_layout.addWidget(atk_table)
    tables_row.addWidget(atk_group)

    defender_allegiance = defenders[0].allegiance if defenders else ""
    def_group = QGroupBox(f"Defender ({defender_allegiance})")
    def_table = UnitTable([UnitColumn.ICON, UnitColumn.NAME, UnitColumn.STATUS])
    def_table.set_units(defenders, game_state)
    def_group_layout = QVBoxLayout(def_group)
    def_group_layout.setContentsMargins(4, 4, 4, 4)
    def_group_layout.addWidget(def_table)
    tables_row.addWidget(def_group)

    layout.addLayout(tables_row)

    if leader_escape_requests:
        leader_names = []
        for req in leader_escape_requests:
            leader = getattr(req, "leader", None)
            if leader:
                leader_names.append(TextFormatter.format_unit_log_string(leader))
        if leader_names:
            escape_label = QLabel(f"{', '.join(leader_names)} trying to escape")
            escape_label.setStyleSheet("font-size: 13px; font-style: italic; color: #cc8800;")
            layout.addWidget(escape_label)

    if advance_available:
        breakthrough_label = QLabel("Breakthrough!")
        breakthrough_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #228B22;")
        layout.addWidget(breakthrough_label)

    layout.addStretch()
    return widget


def _center_view_on_hex(highlight_coords):
    """Center the map view on the given hex and highlight it in red."""
    if highlight_coords is None:
        return
    app = QApplication.instance()
    if app is None:
        return
    parent = app.activeWindow()
    if parent is None:
        return
    map_view = getattr(parent, "map_view", None)
    if map_view is None:
        return
    if hasattr(map_view, "sync_with_model"):
        try:
            map_view.sync_with_model()
        except Exception:
            pass
    if hasattr(map_view, "get_hex_center") and hasattr(map_view, "centerOn"):
        try:
            col, row = highlight_coords
            center_pt = map_view.get_hex_center(col, row)
            map_view.centerOn(center_pt)
        except Exception:
            pass
    try:
        map_view.highlight_movement_range([], [highlight_coords])
    except Exception:
        pass
    QApplication.processEvents()


def show_combat_result_popup(
    game_state,
    title: str,
    attackers,
    defenders,
    resolution,
    context: str | None = None,
    target_hex=None,
):
    """
    Shows combat details in a styled MessageDialog only when:
      - game_state.combat_details == 'verbose'
      - there is at least one human player

    Additionally, while the popup is visible, the target hex (if provided)
    is highlighted in red using the "warning" highlight channel, and the map
    view is centered on that hex.
    """
    # Always center the view on the combat/interception hex
    highlight_coords = _to_offset_coords(target_hex)
    _center_view_on_hex(highlight_coords)

    if not _is_verbose(game_state) or not game_state.has_human_player():
        return

    result = (resolution or {}).get("result", "-/-")
    combat_type = (resolution or {}).get("combat_type", "land")
    rounds = (resolution or {}).get("rounds", None)
    advance_available = bool((resolution or {}).get("advance_available", False))
    leader_escape_requests = (resolution or {}).get("leader_escape_requests", []) or []

    target_hex_str = TextFormatter.format_target_hex(target_hex)
    body_title_text = f"{combat_type.capitalize()} battle at {target_hex_str}"
    icon_name = "intercept.svg" if context == "interception" else "battle.svg"
    icon_path = os.path.join(ICONS_DIR, icon_name)

    combat_data = {
        "title": title,
        "body_title": body_title_text,
        "combat_type": combat_type,
        "target_hex_str": target_hex_str,
        "attackers": attackers,
        "defenders": defenders,
        "leader_escape_requests": leader_escape_requests,
        "advance_available": advance_available,
        "game_state": game_state,
    }
    _enqueue_combat_popup(title, highlight_coords, icon_path, combat_data)

def _enqueue_combat_popup(
    title: str,
    highlight_coords: Optional[Tuple[int, int]] = None,
    icon_path: Optional[str] = None,
    combat_data: Optional[dict] = None,
):
    _PENDING_COMBAT_DIALOGS.append((title, highlight_coords, icon_path, combat_data))
    _drain_combat_popup_queue()

def _drain_combat_popup_queue():
    global _COMBAT_DIALOG_ACTIVE

    if _COMBAT_DIALOG_ACTIVE or not _PENDING_COMBAT_DIALOGS:
        return

    _COMBAT_DIALOG_ACTIVE = True

    app = QApplication.instance()
    parent = app.activeWindow() if app else None
    map_view = getattr(parent, "map_view", None) if parent else None
    had_map_view = bool(map_view and hasattr(map_view, "highlight_movement_range"))

    title, highlight_coords, icon_path, combat_data = _PENDING_COMBAT_DIALOGS.popleft()

    try:
        if had_map_view:
            if hasattr(map_view, "sync_with_model"):
                try:
                    map_view.sync_with_model()
                except Exception:
                    pass

            if highlight_coords is not None:
                if hasattr(map_view, "get_hex_center") and hasattr(map_view, "centerOn"):
                    try:
                        col, row = highlight_coords
                        center_pt = map_view.get_hex_center(col, row)
                        map_view.centerOn(center_pt)
                    except Exception:
                        pass

                try:
                    map_view.highlight_movement_range([], [highlight_coords])
                except Exception:
                    pass

            QApplication.processEvents()

        dialog = MessageDialog(title, "", parent=parent, icon_path=icon_path)
        if combat_data:
            dialog.set_title_text(combat_data.get("body_title", title))
            body_widget = _build_combat_body_widget(
                combat_type=combat_data.get("combat_type", "land"),
                target_hex_str=combat_data.get("target_hex_str", ""),
                attackers=combat_data.get("attackers", []),
                defenders=combat_data.get("defenders", []),
                leader_escape_requests=combat_data.get("leader_escape_requests", []),
                advance_available=combat_data.get("advance_available", False),
                game_state=combat_data.get("game_state"),
            )
            dialog.set_body_widget(body_widget)
        dialog.exec()

    finally:
        if had_map_view:
            try:
                map_view.highlight_movement_range([])
            except Exception:
                pass

        _COMBAT_DIALOG_ACTIVE = False
        if _PENDING_COMBAT_DIALOGS:
            QTimer.singleShot(0, _drain_combat_popup_queue)


class InteractiveUnitTable(UnitTable):
    """
    A UnitTable subclass that supports left-click to allocate damage
    and right-click to de-allocate during manual damage allocation.
    """
    def __init__(self, columns, parent=None):
        super().__init__(columns, parent)
        self.allocations = {}
        self.max_per_unit = {}
        self.setContextMenuPolicy(Qt.NoContextMenu)

    def set_allocation_data(self, allocations, max_per_unit):
        self.allocations = allocations
        self.max_per_unit = max_per_unit

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid():
            super().mousePressEvent(event)
            return
        row = index.row()
        unit = self.current_units[row] if row < len(self.current_units) else None
        if unit is None:
            super().mousePressEvent(event)
            return

        handled = False
        if event.button() == Qt.LeftButton:
            parent = self.parent()
            while parent and not hasattr(parent, "on_unit_allocate"):
                parent = parent.parent()
            if parent:
                parent.on_unit_allocate(unit)
                handled = True
        elif event.button() == Qt.RightButton:
            parent = self.parent()
            while parent and not hasattr(parent, "on_unit_deallocate"):
                parent = parent.parent()
            if parent:
                parent.on_unit_deallocate(unit)
                handled = True
        super().mousePressEvent(event)
        if handled:
            event.accept()

    def update_status_display(self, unit):
        """Update the STATUS cell for a unit based on current allocation."""
        status_col = self.columns_config.index(UnitColumn.STATUS)
        row = self.current_units.index(unit)
        alloc = self.allocations.get(unit, 0)
        item = self.item(row, status_col)

        if alloc == 0:
            item.setText(unit.status.name.title())
            item.setForeground(QColor(0, 0, 0))
        else:
            if unit.status == UnitState.ACTIVE:
                projected = "Depleted" if alloc == 1 else "Reserve"
            else:
                projected = "Reserve"
            item.setText(projected)
            item.setForeground(QColor(200, 0, 0))


class DamageAllocationDialog(QDialog):
    """
    Dialog for human players to manually allocate depletion steps after combat.

    Left-click on a unit row allocates one damage step (if the unit can absorb more).
    Right-click removes one allocation.
    The STATUS column shows the projected status in red when modified.
    OK is disabled until all damage is allocated or all units are at max capacity.
    Auto resets allocations and uses the deterministic auto-allocation logic.
    """
    def __init__(self, units, total_steps, side_name, game_state=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Allocate Damage - {side_name.title()}")
        self.setMinimumSize(420, 320)
        self.setModal(True)

        self.units = list(units)
        self.total_steps = total_steps
        self.remaining = total_steps
        self.game_state = game_state
        self._result_allocations = {}

        self.max_per_unit = {}
        for u in self.units:
            if u.status == UnitState.ACTIVE:
                self.max_per_unit[u] = 2
            elif u.status == UnitState.DEPLETED:
                self.max_per_unit[u] = 1
            else:
                self.max_per_unit[u] = 0

        self.allocations = {u: 0 for u in self.units}

        self._build_ui()
        self._update_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.table = InteractiveUnitTable([UnitColumn.ICON, UnitColumn.NAME, UnitColumn.STATUS], parent=self)
        self.table.set_units(self.units, self.game_state)
        self.table.set_allocation_data(self.allocations, self.max_per_unit)
        layout.addWidget(self.table)

        self.remaining_label = QLabel()
        layout.addWidget(self.remaining_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.auto_btn = QPushButton("Auto")
        self.auto_btn.clicked.connect(self._on_auto)
        btn_layout.addWidget(self.auto_btn)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self.ok_btn)
        layout.addLayout(btn_layout)

    def _update_ui(self):
        max_possible = sum(
            self.max_per_unit[u] - self.allocations[u]
            for u in self.units
        )
        self.remaining_label.setText(
            f"Remaining: {self.remaining} / {self.total_steps}  "
            f"(max allocatable: {max_possible})"
        )
        all_done = self.remaining == 0 or max_possible == 0
        self.ok_btn.setEnabled(all_done)

    def on_unit_allocate(self, unit):
        if unit not in self.allocations:
            return
        if self.remaining <= 0:
            return
        if self.allocations[unit] >= self.max_per_unit.get(unit, 0):
            return
        self.allocations[unit] += 1
        self.remaining -= 1
        self.table.update_status_display(unit)
        self._update_ui()

    def on_unit_deallocate(self, unit):
        if unit not in self.allocations:
            return
        if self.allocations[unit] <= 0:
            return
        self.allocations[unit] -= 1
        self.remaining += 1
        self.table.update_status_display(unit)
        self._update_ui()

    def _on_auto(self):
        for u in self.units:
            self.allocations[u] = 0
        self.remaining = self.total_steps

        candidates = [u for u in self.units if u.is_on_map]
        projected = {u: u.status for u in candidates}
        for _ in range(self.total_steps):
            chosen = None
            for status_filter, is_wing_check in (
                (UnitState.ACTIVE, lambda u: not u.is_wing()),
                (UnitState.DEPLETED, lambda u: not u.is_wing()),
                (UnitState.ACTIVE, lambda u: u.is_flier()),
                (UnitState.DEPLETED, lambda u: u.is_flier()),
            ):
                available = [
                    u for u in candidates
                    if projected[u] == status_filter
                    and is_wing_check(u)
                    and self.allocations[u] < self.max_per_unit.get(u, 0)
                ]
                if available:
                    chosen = min(available, key=lambda u: (getattr(u, "combat_rating", 0), id(u)))
                    break
            if chosen is None:
                break
            self.allocations[chosen] += 1
            self.remaining -= 1
            if projected[chosen] == UnitState.ACTIVE and self.max_per_unit.get(chosen, 0) >= 2:
                projected[chosen] = UnitState.DEPLETED

        for u in self.units:
            self.table.update_status_display(u)
        self._update_ui()

    def _on_ok(self):
        self._result_allocations = {
            u: count for u, count in self.allocations.items() if count > 0
        }
        self.accept()

    def get_allocations(self):
        return self._result_allocations
