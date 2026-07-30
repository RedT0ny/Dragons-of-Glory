from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.content.specs import UnitColumn
from src.content.tools import TextFormatter
from src.gui.unit_panel import UnitTable


def _build_unit_table_group(side_label, units, game_state):
    allegiance = units[0].allegiance if units else ""
    group = QGroupBox(f"{side_label} ({allegiance})")
    table = UnitTable([UnitColumn.ICON, UnitColumn.NAME, UnitColumn.STATUS])
    table.set_units(units, game_state)
    group_layout = QVBoxLayout(group)
    group_layout.setContentsMargins(4, 4, 4, 4)
    group_layout.addWidget(table)
    return group


def _build_tables_row(attackers, defenders, game_state):
    row = QHBoxLayout()
    row.setSpacing(12)
    row.addWidget(_build_unit_table_group("Attacker", attackers, game_state))
    row.addWidget(_build_unit_table_group("Defender", defenders, game_state))
    return row


def show_naval_withdraw_dialog(side_allegiance, round_number, attackers, defenders, game_state=None, parent=None):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox

    dialog = QDialog(parent)
    dialog.setWindowTitle("Naval Withdrawal")
    dialog.setMinimumSize(520, 300)
    layout = QVBoxLayout(dialog)

    round_label = QLabel(f"Round {round_number} result:")
    round_label.setStyleSheet("font-size: 16px; font-weight: bold;")
    layout.addWidget(round_label)

    layout.addLayout(_build_tables_row(attackers, defenders, game_state))

    question = QLabel(f"Should {side_allegiance.capitalize()} withdraw all fleets and end naval combat?")
    question.setStyleSheet("font-size: 14px; margin-top: 12px;")
    layout.addWidget(question)

    buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    return dialog.exec() == QDialog.Accepted


class CombatResultWidget(QWidget):
    def __init__(
        self,
        combat_type: str,
        target_hex_str: str,
        attackers: list,
        defenders: list,
        leader_escape_requests: list,
        advance_available: bool,
        game_state=None,
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addLayout(_build_tables_row(attackers, defenders, game_state))

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
