from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

from src.content.config import CRT_DATA
from src.content.constants import HL, WS, NEUTRAL
from src.content.loader import load_data
from src.content.specs import UnitType, TerrainType, HexsideType
from src.game.combat import CombatResolver
from src.game.map import Hex


@dataclass
class OverlayData:
    kind: str
    values: Dict[Tuple[int, int], object] = field(default_factory=dict)
    min_value: float = 0.0
    max_value: float = 0.0
    meta: Dict[str, object] = field(default_factory=dict)


class OverlayBase:
    name: str = ""

    def compute(self, game_state):
        raise NotImplementedError


class PoliticalMap(OverlayBase):
    name = "political"

    def compute(self, game_state):
        values = {}
        for country in game_state.countries.values():
            for col, row in country.territories:
                values[(int(col), int(row))] = country.id
        return OverlayData(kind="country", values=values)


class ControlMap(OverlayBase):
    name = "control"

    def compute(self, game_state):
        board = game_state.map
        if not board:
            return OverlayData(kind="allegiance", values={})

        occupied = {}
        contested = set()

        def _stack_control_allegiance(units):
            allies = set()
            for u in units:
                if not getattr(u, "is_on_map", False):
                    continue
                if not ((hasattr(u, "is_army") and u.is_army()) or getattr(u, "unit_type", None) == UnitType.WING):
                    continue
                if u.allegiance in (HL, WS):
                    allies.add(u.allegiance)
            if len(allies) == 1:
                return next(iter(allies))
            if len(allies) > 1:
                return "contested"
            return None

        for (q, r), units in board.unit_map.items():
            side = _stack_control_allegiance(units)
            if side is None:
                continue
            if side == "contested":
                contested.add((q, r))
                continue
            occupied[(q, r)] = side

        zoc_by_side = {HL: set(), WS: set()}

        def _hex_is_neutral_country(hex_obj):
            col, row = hex_obj.axial_to_offset()
            country = game_state.get_country_by_hex(col, row)
            return bool(country and country.allegiance == NEUTRAL)

        def _stack_can_project(stack_units, from_hex, to_hex):
            for u in stack_units:
                if not getattr(u, "is_on_map", False):
                    continue
                if not ((hasattr(u, "is_army") and u.is_army()) or getattr(u, "unit_type", None) == UnitType.WING):
                    continue
                if not game_state.can_unit_project_across_hexside(u, from_hex, to_hex):
                    continue
                return True
            return False

        for (q, r), units in board.unit_map.items():
            side = occupied.get((q, r))
            if side not in (HL, WS):
                continue
            from_hex = Hex(q, r)
            for neighbor in from_hex.neighbors():
                if _hex_is_neutral_country(neighbor):
                    continue
                if (neighbor.q, neighbor.r) in occupied and occupied[(neighbor.q, neighbor.r)] != side:
                    continue
                if not _stack_can_project(units, from_hex, neighbor):
                    continue
                zoc_by_side[side].add((neighbor.q, neighbor.r))

        values = {}
        for row in range(board.height):
            for col in range(board.width):
                hex_obj = Hex.offset_to_axial(col, row)
                key = (hex_obj.q, hex_obj.r)
                if _hex_is_neutral_country(hex_obj):
                    continue
                if key in occupied:
                    values[(col, row)] = occupied[key]
                    continue
                if key in contested:
                    values[(col, row)] = "contested"
                    continue
                sides = set()
                for side in (HL, WS):
                    if key in zoc_by_side[side]:
                        sides.add(side)
                if len(sides) == 1:
                    values[(col, row)] = next(iter(sides))
                elif len(sides) > 1:
                    values[(col, row)] = "contested"

        return OverlayData(kind="allegiance", values=values)


class SupplyMap(OverlayBase):
    name = "supply"

    def compute(self, game_state):
        supply_mode = str(getattr(game_state, "supply", "standard")).strip().lower()
        if supply_mode != "advanced":
            return OverlayData(kind="scalar", values={}, min_value=0.0, max_value=0.0)
        side = getattr(game_state, "active_player", None)
        if side not in (HL, WS):
            return OverlayData(kind="scalar", values={}, min_value=0.0, max_value=0.0)
        reach = _compute_supply_reach(game_state, side)
        values = {Hex(q, r).axial_to_offset(): 1.0 for (q, r) in reach}
        return OverlayData(kind="scalar", values=values, min_value=0.0, max_value=1.0)


class TerritoryMap(OverlayBase):
    name = "territory"

    def compute(self, game_state):
        board = game_state.map
        if not board or not getattr(game_state, "scenario_spec", None):
            return OverlayData(kind="allegiance", values={})

        def _stack_control_allegiance(units):
            allies = set()
            for u in units:
                if not getattr(u, "is_on_map", False):
                    continue
                if not ((hasattr(u, "is_army") and u.is_army()) or getattr(u, "unit_type", None) == UnitType.WING):
                    continue
                if u.allegiance in (HL, WS):
                    allies.add(u.allegiance)
            if len(allies) == 1:
                return next(iter(allies))
            if len(allies) > 1:
                return "contested"
            return None

        values = game_state.compute_territory_baseline()

        for (col, row), value in (game_state.territory_overrides or {}).items():
            if value in (HL, WS, "contested"):
                values[(int(col), int(row))] = value

        # Step 4: live unit-occupation overlay (occupied + adjacent ZOC)
        occupied = {}
        occupied_contested = set()

        for (q, r), units in board.unit_map.items():
            side = _stack_control_allegiance(units)
            if side is None:
                continue
            if side == "contested":
                occupied_contested.add((q, r))
                continue
            occupied[(q, r)] = side

        def _stack_can_project(stack_units, from_hex, to_hex):
            for u in stack_units:
                if not getattr(u, "is_on_map", False):
                    continue
                if not ((hasattr(u, "is_army") and u.is_army()) or getattr(u, "unit_type", None) == UnitType.WING):
                    continue
                if not game_state.can_unit_project_across_hexside(u, from_hex, to_hex):
                    continue
                return True
            return False

        zoc_by_side = {HL: set(), WS: set()}
        for (q, r), units in board.unit_map.items():
            side = occupied.get((q, r))
            if side not in (HL, WS):
                continue
            from_hex = Hex(q, r)
            for neighbor in from_hex.neighbors():
                if (neighbor.q, neighbor.r) in occupied and occupied[(neighbor.q, neighbor.r)] != side:
                    continue
                if not _stack_can_project(units, from_hex, neighbor):
                    continue
                zoc_by_side[side].add((neighbor.q, neighbor.r))

        for (q, r), side in occupied.items():
            col, row = Hex(q, r).axial_to_offset()
            values[(col, row)] = side
        for (q, r) in occupied_contested:
            col, row = Hex(q, r).axial_to_offset()
            values[(col, row)] = "contested"

        zoc_keys = zoc_by_side[HL] | zoc_by_side[WS]
        for q, r in zoc_keys:
            if (q, r) in occupied or (q, r) in occupied_contested:
                continue
            sides = set()
            for side in (HL, WS):
                if (q, r) in zoc_by_side[side]:
                    sides.add(side)
            col, row = Hex(q, r).axial_to_offset()
            if len(sides) == 1:
                values[(col, row)] = next(iter(sides))
            elif len(sides) > 1:
                values[(col, row)] = "contested"

        return OverlayData(kind="allegiance", values=values)


class InfluenceMap(OverlayBase):
    def __init__(self, side: str):
        self.side = side
        self.name = f"{side}_power"

    def compute(self, game_state):
        board = game_state.map
        if not board:
            return OverlayData(kind="scalar", values={})

        values = {}
        for unit in game_state.units:
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "allegiance", None) != self.side:
                continue
            if not game_state.is_combat_unit(unit):
                continue

            if not getattr(unit, "position", None) or unit.position[0] is None or unit.position[1] is None:
                continue

            start_hex = Hex.offset_to_axial(*unit.position)

            if unit.unit_type == UnitType.FLEET:
                for (q, r), units in board.unit_map.items():
                    target_hex = Hex(q, r)
                    if game_state.can_fleet_attack_hex(unit, target_hex):
                        col, row = target_hex.axial_to_offset()
                        values[(col, row)] = values.get((col, row), 0.0) + float(unit.combat_rating or 0)
                continue

            for neighbor in start_hex.neighbors():
                if not game_state.can_unit_project_across_hexside(unit, start_hex, neighbor):
                    continue
                col, row = neighbor.axial_to_offset()
                values[(col, row)] = values.get((col, row), 0.0) + float(unit.combat_rating or 0)

        min_val, max_val = _min_max(values)
        return OverlayData(kind="scalar", values=values, min_value=min_val, max_value=max_val)


class ThreatMap(OverlayBase):
    name = "threat"
    _expected_loss_by_odds = None

    def compute(self, game_state):
        active = getattr(game_state, "active_player", None)
        enemy = _enemy_of(active)
        if active not in (HL, WS) or enemy is None:
            return OverlayData(kind="scalar", values={})

        friendly = InfluenceMap(active).compute(game_state)
        enemy_power = InfluenceMap(enemy).compute(game_state)
        loss_by_odds = self._get_expected_loss_by_odds()
        values = {}
        max_val = 0.0

        for key, f_power in friendly.values.items():
            e_power = enemy_power.values.get(key, 0.0)
            odds_str = CombatResolver.calculate_odds(f_power, e_power)
            expected_loss = loss_by_odds.get(odds_str, 0.0)
            values[key] = expected_loss
            max_val = max(max_val, expected_loss)

        return OverlayData(kind="scalar", values=values, min_value=0.0, max_value=max_val)

    def _get_expected_loss_by_odds(self):
        if self.__class__._expected_loss_by_odds is not None:
            return self.__class__._expected_loss_by_odds
        crt_data = load_data(CRT_DATA)
        odds_columns = set()
        for row in crt_data.values():
            odds_columns.update(row.keys())
        expected = {}
        for odds in odds_columns:
            losses = []
            for roll in sorted(crt_data.keys()):
                result = crt_data[roll].get(odds)
                if result is None:
                    continue
                attacker_result = str(result).split("/")[0]
                losses.append(_estimate_loss_from_result(attacker_result))
            expected[odds] = sum(losses) / len(losses) if losses else 0.0
        self.__class__._expected_loss_by_odds = expected
        return expected

def _min_max(values: Dict[Tuple[int, int], float]):
    if not values:
        return 0.0, 0.0
    mins = min(values.values())
    maxs = max(values.values())
    return float(mins), float(maxs)

def _enemy_of(side: Optional[str]):
    if side == HL:
        return WS
    if side == WS:
        return HL
    return None

def _estimate_loss_from_result(result: str) -> float:
    if not result or result == "-":
        return 0.0
    loss = 0.0
    if "E" in result:
        loss += 1.0
    if "D" in result:
        loss += 0.5
    for ch in result:
        if ch.isdigit():
            loss += 0.5 * int(ch)
    return loss

def _compute_supply_reach(game_state, allegiance: str):
    board = game_state.map
    friendly_locations = {
        (q, r)
        for (q, r), loc in getattr(board, "locations", {}).items()
        if getattr(loc, "occupier", None) == allegiance
    }
    if not friendly_locations:
        return set()

    class _Sample:
        def __init__(self, side):
            self.allegiance = side

    sample_unit = _Sample(allegiance)

    frontier = [Hex(q, r) for (q, r) in friendly_locations]
    visited = set(friendly_locations)
    while frontier:
        current = frontier.pop(0)
        for neighbor in current.neighbors():
            nk = (neighbor.q, neighbor.r)
            if nk in visited:
                continue
            if not game_state._is_valid_supply_step(current, neighbor, allegiance, sample_unit):
                continue
            visited.add(nk)
            frontier.append(neighbor)
    return visited
