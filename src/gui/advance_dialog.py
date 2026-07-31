from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
)
from src.gui.unit_panel import UnitTable
from src.content.specs import UnitColumn
from src.content.config import GAME_ICON


def show_advance_dialog(candidates, game_state):
    """Show a dialog letting the human player choose which units advance after combat.

    Args:
        candidates: list of Unit objects eligible to advance.
        game_state: current GameState (needed by UnitTable for display data).

    Returns:
        list of chosen Unit objects, or [] if the player cancelled.
    """
    if not candidates:
        return []

    dlg = QDialog(None)
    dlg.setWindowTitle("Advance after combat")
    dlg.setMinimumSize(450, 300)
    dlg.setWindowIcon(QIcon(GAME_ICON))

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 16, 16, 16)

    title_label = QLabel("Select units to advance:")
    title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
    layout.addWidget(title_label)

    columns = [
        UnitColumn.CHECKBOX, UnitColumn.ICON, UnitColumn.NAME,
        UnitColumn.STATUS, UnitColumn.POS,
    ]
    table = UnitTable(columns, parent=dlg)
    table.set_units(candidates, game_state)
    table.setMaximumHeight(400)

    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item and (item.flags() & Qt.ItemIsEnabled):
            item.setCheckState(Qt.Checked)

    layout.addWidget(table)

    btn_layout = QHBoxLayout()
    btn_layout.addStretch()
    advance_btn = QPushButton("Advance")
    advance_btn.clicked.connect(dlg.accept)
    cancel_btn = QPushButton("Cancel")
    cancel_btn.clicked.connect(dlg.reject)
    btn_layout.addWidget(advance_btn)
    btn_layout.addWidget(cancel_btn)
    layout.addLayout(btn_layout)

    if dlg.exec() == QDialog.Accepted:
        chosen = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                unit = item.data(Qt.UserRole)
                if unit:
                    chosen.append(unit)
        return chosen

    return []
