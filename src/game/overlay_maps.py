from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

from src.content.config import CRT_DATA
from src.content.constants import HL, WS, NEUTRAL
from src.content.loader import load_data
from src.content.specs import UnitType, TerrainType, HexsideType
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
                if not u.is_control_unit():
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
                if not u.is_control_unit():
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
                if not u.is_control_unit():
                    continue
                if u.allegiance in (HL, WS):
                    allies.add(u.allegiance)
            if len(allies) == 1:
                return next(iter(allies))
            if len(allies) > 1:
                return "contested"
            return None

        values = game_state.compute_territory_baseline()
        scenario_seeds = game_state._compute_territory_scenario_baseline()

        def _hex_is_neutral_country(hex_obj):
            col, row = hex_obj.axial_to_offset()
            country = game_state.get_country_by_hex(col, row)
            return bool(country and country.allegiance == NEUTRAL)

        def _neutral_seed_allows(side, hex_obj):
            if not _hex_is_neutral_country(hex_obj):
                return True
            col, row = hex_obj.axial_to_offset()
            seed = scenario_seeds.get((col, row))
            return seed in (side, "contested")

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
                if not u.is_control_unit():
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
                side = next(iter(sides))
                if not _neutral_seed_allows(side, Hex(q, r)):
                    continue
                values[(col, row)] = side
            elif len(sides) > 1:
                if _hex_is_neutral_country(Hex(q, r)):
                    seed = scenario_seeds.get((col, row))
                    if seed != "contested":
                        continue
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
    _expected_defender_loss_by_odds = None

    def compute(self, game_state):
        active = getattr(game_state, "active_player", None)
        enemy = _enemy_of(active)
        if active not in (HL, WS) or enemy is None:
            return OverlayData(kind="scalar", values={})
        board = game_state.map
        if not board:
            return OverlayData(kind="scalar", values={})

        friendly = InfluenceMap(active).compute(game_state)
        enemy_power = InfluenceMap(enemy).compute(game_state)
        loss_by_odds = self._get_expected_defender_loss_by_odds()
        occupied, contested_occupied, zoc_by_side = self._compute_zoc(game_state)
        enemy_occupied = {coord for coord, side in occupied.items() if side == enemy}
        defender_ref = self._reference_defender_strength(game_state, active)
        values = {}
        max_val = 0.0

        for row in range(board.height):
            for col in range(board.width):
                hex_obj = Hex.offset_to_axial(col, row)
                terrain = board.get_terrain(hex_obj)
                if terrain in (TerrainType.OCEAN, TerrainType.MAELSTROM):
                    continue
                e_power = float(enemy_power.values.get((col, row), 0.0))
                defender_strength = self._adjust_defender_strength(defender_ref, board, hex_obj)
                odds_str = _odds_from_power(e_power, defender_strength)
                expected_loss = 0.0 if e_power <= 0 else float(loss_by_odds.get(odds_str, 0.0))

                enemy_only_zoc = self._enemy_only_zoc(hex_obj, active, enemy, zoc_by_side)
                has_enemy_pressure = (e_power > 0.0) or enemy_only_zoc
                if not has_enemy_pressure:
                    expected_loss = 0.0
                    retreat_penalty = 0.0
                    enemy_only_zoc_penalty = 0.0
                    location_penalty = 0.0
                else:
                    retreat_penalty = self._retreat_penalty(
                        game_state,
                        hex_obj,
                        active,
                        enemy,
                        zoc_by_side,
                        enemy_occupied,
                        contested_occupied,
                    )
                    enemy_only_zoc_penalty = 0.5 if enemy_only_zoc else 0.0
                    location_penalty = 0.5 if board.get_location(hex_obj) else 0.0

                support = float(friendly.values.get((col, row), 0.0))
                support_discount = min(1.0, support / max(1.0, defender_strength)) * 0.5

                threat = max(0.0, expected_loss + retreat_penalty + enemy_only_zoc_penalty + location_penalty - support_discount)
                if threat <= 0:
                    continue
                values[(col, row)] = threat
                max_val = max(max_val, threat)

        return OverlayData(
            kind="scalar",
            values=values,
            min_value=0.0,
            max_value=max_val,
            meta={"side": active, "perspective": "defender"},
        )

    def _get_expected_defender_loss_by_odds(self):
        if self.__class__._expected_defender_loss_by_odds is not None:
            return self.__class__._expected_defender_loss_by_odds
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
                defender_result = str(result).split("/")[-1]
                losses.append(_estimate_loss_from_result(defender_result))
            expected[odds] = sum(losses) / len(losses) if losses else 0.0
        self.__class__._expected_defender_loss_by_odds = expected
        return expected

    def _compute_zoc(self, game_state):
        board = game_state.map
        occupied = {}
        contested_occupied = set()
        zoc_by_side = {HL: set(), WS: set()}

        def _stack_control_allegiance(units):
            allies = set()
            for u in units:
                if not getattr(u, "is_on_map", False):
                    continue
                if not u.is_control_unit():
                    continue
                if u.allegiance in (HL, WS):
                    allies.add(u.allegiance)
            if len(allies) == 1:
                return next(iter(allies))
            if len(allies) > 1:
                return "contested"
            return None

        def _stack_can_project(stack_units, from_hex, to_hex):
            for u in stack_units:
                if not getattr(u, "is_on_map", False):
                    continue
                if not u.is_control_unit():
                    continue
                if not game_state.can_unit_project_across_hexside(u, from_hex, to_hex):
                    continue
                return True
            return False

        for (q, r), units in board.unit_map.items():
            side = _stack_control_allegiance(units)
            if side == "contested":
                contested_occupied.add((q, r))
                continue
            if side in (HL, WS):
                occupied[(q, r)] = side

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

        return occupied, contested_occupied, zoc_by_side

    def _reference_defender_strength(self, game_state, side):
        ratings = [
            float(getattr(u, "combat_rating", 0) or 0)
            for u in game_state.units
            if getattr(u, "is_on_map", False)
            and getattr(u, "allegiance", None) == side
            and u.is_control_unit()
        ]
        if not ratings:
            return 4.0
        return max(1.0, sum(ratings) / len(ratings))

    def _adjust_defender_strength(self, base_strength, board, hex_obj):
        strength = float(base_strength)
        terrain = board.get_terrain(hex_obj)
        if terrain == TerrainType.MOUNTAIN:
            strength += 1.5
        elif terrain == TerrainType.FOREST:
            strength += 0.5
        elif terrain == TerrainType.JUNGLE:
            strength += 0.5

        loc = board.get_location(hex_obj)
        if loc and hasattr(loc, "get_defense_modifier"):
            mod = float(loc.get_defense_modifier() or 0.0)
            if mod < 0:
                strength += abs(mod) * 0.25

        defensive_sides = 0
        for neighbor in hex_obj.neighbors():
            hexside = board.get_effective_hexside(hex_obj, neighbor)
            if board._hexside_is(hexside, HexsideType.RIVER):
                defensive_sides += 1
            elif board._hexside_is(hexside, HexsideType.DEEP_RIVER):
                defensive_sides += 1
            elif board._hexside_is(hexside, HexsideType.MOUNTAIN):
                defensive_sides += 1
        strength += min(1.5, defensive_sides * 0.2)
        return max(1.0, strength)

    def _enemy_only_zoc(self, hex_obj, active, enemy, zoc_by_side):
        key = (hex_obj.q, hex_obj.r)
        return key in zoc_by_side.get(enemy, set()) and key not in zoc_by_side.get(active, set())

    def _retreat_penalty(self, game_state, hex_obj, active, enemy, zoc_by_side, enemy_occupied, contested_occupied):
        board = game_state.map
        safe_exits = 0
        for neighbor in hex_obj.neighbors():
            if not board._is_valid_local_hex(neighbor):
                continue
            terrain = board.get_terrain(neighbor)
            if terrain in (TerrainType.OCEAN, TerrainType.MAELSTROM):
                continue
            if (neighbor.q, neighbor.r) in enemy_occupied:
                continue
            if (neighbor.q, neighbor.r) in contested_occupied:
                continue
            if self._enemy_only_zoc(neighbor, active, enemy, zoc_by_side):
                continue
            if not game_state.can_control_probe_project_across_hexside(hex_obj, neighbor, active):
                continue
            safe_exits += 1

        if safe_exits <= 0:
            return 1.5
        if safe_exits == 1:
            return 0.75
        return 0.0

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

def _odds_from_power(attacker: float, defender: float) -> str:
    if defender <= 0: return "6:1"
    ratio = attacker / defender

    if ratio >= 6: return "6:1"
    if ratio >= 5: return "5:1"
    if ratio >= 4: return "4:1"
    if ratio >= 3: return "3:1"
    if ratio >= 2: return "2:1"
    if ratio >= 1.5: return "3:2"
    if ratio >= 1: return "1:1"
    if ratio >= 0.66: return "2:3"
    if ratio >= 0.5: return "1:2"

    return "1:3"

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
