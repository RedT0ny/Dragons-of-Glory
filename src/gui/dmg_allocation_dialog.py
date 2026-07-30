from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.content.specs import UnitColumn, UnitState
from src.gui.unit_panel import InteractiveUnitTable


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
        """ Automatically allocate damage steps based on the following priority:
            1. Active non-wing units
            2. Depleted non-wing units
            3. Active flier units
            4. Depleted flier units
        Within each category, units with lower combat rating are prioritized.
        """
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
