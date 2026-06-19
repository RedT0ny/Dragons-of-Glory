from collections import deque
import os
from typing import Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.content.config import ICONS_DIR
from src.content.specs import UnitColumn
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
    if not _is_verbose(game_state) or not game_state.has_human_player():
        return

    result = (resolution or {}).get("result", "-/-")
    combat_type = (resolution or {}).get("combat_type", "land")
    rounds = (resolution or {}).get("rounds", None)
    advance_available = bool((resolution or {}).get("advance_available", False))
    leader_escape_requests = (resolution or {}).get("leader_escape_requests", []) or []

    target_hex_str = TextFormatter.format_target_hex(target_hex)
    body_title_text = f"{combat_type.capitalize()} battle at {target_hex_str}"

    highlight_coords = _to_offset_coords(target_hex)
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
    QTimer.singleShot(0, _drain_combat_popup_queue)

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
