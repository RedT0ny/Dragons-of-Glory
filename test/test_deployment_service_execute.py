from types import SimpleNamespace

from src.content.constants import HL
from src.content.specs import UnitState
from src.game.deployment import DeploymentService
from src.game.map import Hex


class FakeMap:
    def __init__(self, can_land=True, can_stack=True):
        self._can_land = can_land
        self._can_stack = can_stack

    def can_unit_land_on_hex(self, unit, target_hex):
        return self._can_land

    def can_stack_move_to(self, units, target_hex):
        return self._can_stack


def _unit():
    return SimpleNamespace(
        id="u1",
        land="icewall",
        status=UnitState.READY,
        movement_points=3,
    )


def test_deploy_unit_rejects_invalid_terrain():
    moved = []
    gs = SimpleNamespace(
        map=FakeMap(can_land=False, can_stack=True),
        move_unit=lambda unit, target_hex: moved.append((unit, target_hex)),
    )
    service = DeploymentService(gs)
    unit = _unit()

    result = service.deploy_unit(unit, Hex(0, 0))

    assert result.success is False
    assert "invalid terrain" in (result.error or "")
    assert moved == []


def test_deploy_unit_sets_active_and_applies_hl_invasion_lock():
    moved = []
    gs = SimpleNamespace(
        map=FakeMap(can_land=True, can_stack=True),
        move_unit=lambda unit, target_hex: moved.append((unit, target_hex)),
    )
    service = DeploymentService(gs)
    unit = _unit()

    result = service.deploy_unit(
        unit,
        Hex(1, 2),
        invasion_deployment_active=True,
        invasion_deployment_allegiance=HL,
        invasion_deployment_country_id="icewall",
    )

    assert result.success is True
    assert unit.status == UnitState.ACTIVE
    assert unit.movement_points == 0
    assert len(moved) == 1
