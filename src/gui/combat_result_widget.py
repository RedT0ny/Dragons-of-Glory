from PySide6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

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
    from src.content.specs import LocType
    from src.game.map import Hex

    dialog = QDialog(parent)
    dialog.setWindowTitle("Naval Withdrawal")
    dialog.setMinimumSize(520, 300)
    layout = QVBoxLayout(dialog)

    round_label = QLabel(f"Round {round_number} result:")
    round_label.setStyleSheet("font-size: 16px; font-weight: bold;")
    layout.addWidget(round_label)

    tables_widget = QWidget()
    tables_widget.setLayout(_build_tables_row(attackers, defenders, game_state))
    tables_scroll = QScrollArea()
    tables_scroll.setWidgetResizable(True)
    tables_scroll.setFrameShape(QFrame.NoFrame)
    tables_scroll.setMaximumHeight(400)
    tables_scroll.setWidget(tables_widget)
    layout.addWidget(tables_scroll)

    is_defender = bool(defenders) and defenders[0].allegiance == side_allegiance
    defending_port = False
    if is_defender and game_state and defenders:
        fleet = defenders[0]
        if fleet.position and None not in fleet.position:
            hex_coord = Hex.offset_to_axial(*fleet.position)
            loc = game_state.map.get_location(hex_coord)
            defending_port = bool(loc and loc.loc_type == LocType.PORT.value and loc.occupier == side_allegiance)

    question = QLabel(f"Should {side_allegiance.capitalize()} withdraw all fleets and end naval combat?")
    question.setStyleSheet("font-size: 14px; margin-top: 12px;")
    layout.addWidget(question)

    if defending_port:
        port_note = QLabel("Fleets defending a port cannot withdraw.")
        port_note.setStyleSheet("font-size: 12px; color: #cc4400; font-style: italic;")
        layout.addWidget(port_note)

    buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)

    if defending_port:
        yes_button = buttons.button(QDialogButtonBox.Yes)
        yes_button.setEnabled(False)

    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    return dialog.exec() == QDialog.Accepted


def ask_naval_withdraw(game_state, side_allegiance, round_number, attackers, defenders, parent=None):
    """Ask a human side whether to withdraw from naval combat.

    AI sides (and sides with no player entry) decide automatically and no
    dialog is shown.  Returns True when the side chooses to withdraw.
    """
    player = game_state.players.get(side_allegiance) if game_state else None
    if not player or getattr(player, "is_ai", True):
        return False
    return show_naval_withdraw_dialog(
        side_allegiance,
        round_number,
        attackers,
        defenders,
        game_state=game_state,
        parent=parent,
    )


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

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
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

        scroll.setWidget(content)
