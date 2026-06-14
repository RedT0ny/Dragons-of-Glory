from collections import deque
import os
from typing import Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.content.config import ICONS_DIR
from src.content.tools import TextFormatter
from src.gui.message_dialog import MessageDialog

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
    leader_escapes = len((resolution or {}).get("leader_escape_requests", []) or [])

    lines = [
        f"Context: {context or 'combat'}",
        f"Hex: {TextFormatter.format_target_hex(target_hex)}",
        f"Type: {combat_type}",
        f"Result: {result}",
        f"Attackers: {TextFormatter.format_units(attackers)}",
        f"Defenders: {TextFormatter.format_units(defenders)}",
        f"Leader escapes: {leader_escapes}",
        f"Advance available: {advance_available}",
    ]
    if rounds is not None:
        lines.append(f"Rounds: {rounds}")

    message = "\n".join(lines)

    highlight_coords = _to_offset_coords(target_hex)
    icon_name = "intercept.svg" if context == "interception" else "battle.svg"
    icon_path = os.path.join(ICONS_DIR, icon_name)
    _enqueue_combat_popup(title, message, highlight_coords, icon_path)

def _enqueue_combat_popup(
    title: str,
    message: str,
    highlight_coords: Optional[Tuple[int, int]] = None,
    icon_path: Optional[str] = None,
):
    _PENDING_COMBAT_DIALOGS.append((title, message, highlight_coords, icon_path))
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

    title, message, highlight_coords, icon_path = _PENDING_COMBAT_DIALOGS.popleft()

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

        dialog = MessageDialog(title, message, parent=parent, icon_path=icon_path)
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
