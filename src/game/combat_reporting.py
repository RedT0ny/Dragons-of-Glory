from collections import deque
from typing import Iterable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src.content.text_formatter import TextFormatter

_PENDING_COMBAT_DIALOGS = deque()
_COMBAT_DIALOG_ACTIVE = False


def _is_verbose(game_state) -> bool:
    return str(getattr(game_state, "combat_details", "brief")).strip().lower() == "verbose"


def _has_human_player(game_state) -> bool:
    players = getattr(game_state, "players", {}) or {}
    return any(not getattr(player, "is_ai", False) for player in players.values())

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
    Shows combat details in a QMessageBox only when game_state.combat_details == 'verbose'.
    """
    if context == "interception":
        if not _is_verbose(game_state) or not _has_human_player(game_state):
            return
    elif not _is_verbose(game_state):
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
    if context == "interception":
        _show_interception_popup(title, message, target_hex)
        return
    _enqueue_combat_popup(title, message)


def _show_interception_popup(title: str, message: str, target_hex):
    app = QApplication.instance()
    parent = app.activeWindow() if app else None
    map_view = getattr(parent, "map_view", None) if parent else None
    had_map_view = bool(map_view and hasattr(map_view, "highlight_movement_range"))
    highlight_coords = None
    if target_hex is not None and hasattr(target_hex, "axial_to_offset"):
        highlight_coords = target_hex.axial_to_offset()
    elif isinstance(target_hex, (tuple, list)) and len(target_hex) == 2:
        highlight_coords = (target_hex[0], target_hex[1])

    try:
        if had_map_view:
            if hasattr(map_view, "sync_with_model"):
                map_view.sync_with_model()
            if highlight_coords is not None:
                map_view.highlight_movement_range([], [highlight_coords])
            QApplication.processEvents()
        QMessageBox.information(parent, title, message)
    finally:
        if had_map_view:
            map_view.highlight_movement_range([])


def _enqueue_combat_popup(title: str, message: str):
    _PENDING_COMBAT_DIALOGS.append((title, message))
    QTimer.singleShot(0, _drain_combat_popup_queue)


def _drain_combat_popup_queue():
    global _COMBAT_DIALOG_ACTIVE
    if _COMBAT_DIALOG_ACTIVE or not _PENDING_COMBAT_DIALOGS:
        return

    _COMBAT_DIALOG_ACTIVE = True
    try:
        app = QApplication.instance()
        parent = app.activeWindow() if app else None
        title, message = _PENDING_COMBAT_DIALOGS.popleft()
        QMessageBox.information(parent, title, message)
    finally:
        _COMBAT_DIALOG_ACTIVE = False
        if _PENDING_COMBAT_DIALOGS:
            QTimer.singleShot(0, _drain_combat_popup_queue)
