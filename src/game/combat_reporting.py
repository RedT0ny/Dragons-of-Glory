from collections import deque
from typing import Iterable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox


_PENDING_COMBAT_DIALOGS = deque()
_COMBAT_DIALOG_ACTIVE = False


def _is_verbose(game_state) -> bool:
    return str(getattr(game_state, "combat_details", "brief")).strip().lower() == "verbose"


def _unit_label(unit) -> str:
    return f"{getattr(unit, 'id', '?')}#{int(getattr(unit, 'ordinal', 1))}"


def _format_units(units: Iterable[object]) -> str:
    return ", ".join(_unit_label(u) for u in units) if units else "-"


def show_combat_result_popup(game_state, title: str, attackers, defenders, resolution, context: str | None = None):
    """
    Shows combat details in a QMessageBox only when game_state.combat_details == 'verbose'.
    """
    if not _is_verbose(game_state):
        return

    result = (resolution or {}).get("result", "-/-")
    combat_type = (resolution or {}).get("combat_type", "land")
    rounds = (resolution or {}).get("rounds", None)
    advance_available = bool((resolution or {}).get("advance_available", False))
    leader_escapes = len((resolution or {}).get("leader_escape_requests", []) or [])

    lines = [
        f"Context: {context or 'combat'}",
        f"Type: {combat_type}",
        f"Result: {result}",
        f"Attackers: {_format_units(attackers)}",
        f"Defenders: {_format_units(defenders)}",
        f"Leader escapes: {leader_escapes}",
        f"Advance available: {advance_available}",
    ]
    if rounds is not None:
        lines.append(f"Rounds: {rounds}")

    _enqueue_combat_popup(title, "\n".join(lines))


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
