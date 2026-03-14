from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Dict, Set, Tuple

from src.content.constants import HL, WS, NEUTRAL
from src.game.map import Hex


@dataclass
class ControlFacts:
    occupied: Dict[Tuple[int, int], str]
    occupied_contested: Set[Tuple[int, int]]
    zoc_by_side: Dict[str, Set[Tuple[int, int]]]


def compute_control_facts(game_state) -> ControlFacts:
    board = game_state.map
    if not board:
        return ControlFacts(occupied={}, occupied_contested=set(), zoc_by_side={HL: set(), WS: set()})

    occupied: Dict[Tuple[int, int], str] = {}
    occupied_contested: Set[Tuple[int, int]] = set()
    zoc_by_side: Dict[str, Set[Tuple[int, int]]] = {HL: set(), WS: set()}

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
            occupied_contested.add((q, r))
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

    return ControlFacts(occupied=occupied, occupied_contested=occupied_contested, zoc_by_side=zoc_by_side)


def is_neutral_country_hex(game_state, hex_obj) -> bool:
    col, row = hex_obj.axial_to_offset()
    country = game_state.get_country_by_hex(col, row)
    return bool(country and country.allegiance == NEUTRAL)


def neutral_seed_allows(game_state, scenario_seeds: Dict[Tuple[int, int], str], side: str, hex_obj) -> bool:
    if not is_neutral_country_hex(game_state, hex_obj):
        return True
    col, row = hex_obj.axial_to_offset()
    seed = scenario_seeds.get((col, row))
    return seed in (side, "contested")


def compute_territory_scenario_baseline(game_state) -> Dict[Tuple[int, int], str]:
    if not game_state.scenario_spec:
        return {}
    setup = getattr(game_state.scenario_spec, "setup", {}) or {}
    seeds = {HL: set(), WS: set()}
    contested = set()

    def add_seed(side, coord):
        other = WS if side == HL else HL
        if coord in seeds[other]:
            seeds[other].discard(coord)
            contested.add(coord)
            return
        if coord in contested:
            return
        seeds[side].add(coord)

    def add_country_territories(side, country_id):
        country = game_state.countries.get(country_id)
        if not country:
            return
        for col, row in country.territories:
            add_seed(side, (int(col), int(row)))

    def add_deployment_entry(side, entry):
        if isinstance(entry, str):
            add_country_territories(side, entry)
            return
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            try:
                col, row = int(entry[0]), int(entry[1])
            except Exception:
                return
            add_seed(side, (col, row))

    def consume_deployment_area(side, deployment_area):
        if deployment_area is None:
            return
        if isinstance(deployment_area, str):
            if deployment_area.lower() == "country_based":
                return
            add_country_territories(side, deployment_area)
            return
        if isinstance(deployment_area, dict):
            countries = deployment_area.get("countries") or []
            coords = deployment_area.get("coords") or []
            hexes = deployment_area.get("hexes") or []
            for cid in countries:
                if isinstance(cid, str):
                    add_country_territories(side, cid)
            for entry in list(coords) + list(hexes):
                add_deployment_entry(side, entry)
            return
        if isinstance(deployment_area, list):
            for entry in deployment_area:
                add_deployment_entry(side, entry)

    for side in (HL, WS):
        side_setup = setup.get(side, {}) or {}
        countries = side_setup.get("countries") or {}
        for cid in countries.keys():
            if isinstance(cid, str):
                add_country_territories(side, cid)
        consume_deployment_area(side, side_setup.get("deployment_area"))

    values = {}
    for col, row in seeds[HL]:
        values[(col, row)] = HL
    for col, row in seeds[WS]:
        values[(col, row)] = WS
    for col, row in contested:
        values[(col, row)] = "contested"
    return values


def apply_country_territory_overrides(game_state, values: Dict[Tuple[int, int], str]) -> Dict[Tuple[int, int], str]:
    for country in game_state.countries.values():
        allegiance = getattr(country, "allegiance", None)
        for col, row in country.territories:
            key = (int(col), int(row))
            if allegiance in (HL, WS):
                values[key] = allegiance
            else:
                values.pop(key, None)
    return values


def compute_territory_baseline(game_state) -> Dict[Tuple[int, int], str]:
    values = compute_territory_scenario_baseline(game_state)
    return apply_country_territory_overrides(game_state, values)


def compute_territory_overrides(game_state) -> Dict[Tuple[int, int], str]:
    if not game_state.map or not game_state.scenario_spec:
        return {}

    baseline = compute_territory_baseline(game_state)
    scenario_seeds = compute_territory_scenario_baseline(game_state)
    overrides = dict(getattr(game_state, "territory_overrides", {}) or {})
    board = game_state.map

    control = compute_control_facts(game_state)
    occupied = control.occupied
    occupied_contested = control.occupied_contested
    zoc_by_side = control.zoc_by_side

    def build_capture_set(side):
        enemy = WS if side == HL else HL
        enemy_occupied = {coord for coord, s in occupied.items() if s == enemy}
        enemy_only_zoc = zoc_by_side[enemy] - zoc_by_side[side]

        anchors = set()
        frontier = set()

        for (q, r), loc in getattr(board, "locations", {}).items():
            if getattr(loc, "occupier", None) == side:
                anchors.add((q, r))

        for (q, r), occ_side in occupied.items():
            if occ_side == side:
                anchors.add((q, r))
                frontier.add((q, r))

        for (col, row), value in overrides.items():
            if value != side:
                continue
            hex_obj = Hex.offset_to_axial(col, row)
            anchors.add((hex_obj.q, hex_obj.r))

        for q, r in zoc_by_side[side]:
            if neutral_seed_allows(game_state, scenario_seeds, side, Hex(q, r)):
                frontier.add((q, r))

        if not anchors or not frontier:
            return set()

        visited = set()
        parent = {}
        queue = deque()

        for anchor in anchors:
            queue.append(anchor)
            visited.add(anchor)
            parent[anchor] = None

        def can_step(from_hex, to_hex):
            if not board._is_valid_local_hex(to_hex):
                return False
            key = (to_hex.q, to_hex.r)
            if key in enemy_occupied:
                return False
            if key in enemy_only_zoc:
                return False
            if not neutral_seed_allows(game_state, scenario_seeds, side, to_hex):
                return False
            return bool(game_state.can_control_probe_project_across_hexside(from_hex, to_hex, side))

        while queue:
            current = queue.popleft()
            current_hex = Hex(*current)
            for neighbor in current_hex.neighbors():
                nk = (neighbor.q, neighbor.r)
                if nk in visited:
                    continue
                if not can_step(current_hex, neighbor):
                    continue
                visited.add(nk)
                parent[nk] = current
                queue.append(nk)

        captured = set()
        for f_hex in frontier:
            if f_hex not in visited:
                continue
            cursor = f_hex
            while cursor is not None:
                captured.add(cursor)
                cursor = parent.get(cursor)

        if captured:
            extra = set()
            for q, r in captured:
                hex_obj = Hex(q, r)
                for neighbor in hex_obj.neighbors():
                    nk = (neighbor.q, neighbor.r)
                    if nk in enemy_occupied or nk in enemy_only_zoc:
                        continue
                    if not neutral_seed_allows(game_state, scenario_seeds, side, neighbor):
                        continue
                    if nk in zoc_by_side[side]:
                        extra.add(nk)
            captured |= extra

        return captured

    captured_by_side = {
        HL: build_capture_set(HL),
        WS: build_capture_set(WS),
    }

    desired = dict(overrides)

    for side in (HL, WS):
        for q, r in captured_by_side[side]:
            col, row = Hex(q, r).axial_to_offset()
            desired[(col, row)] = side

    for q, r in (captured_by_side[HL] & captured_by_side[WS]):
        col, row = Hex(q, r).axial_to_offset()
        desired[(col, row)] = "contested"

    for (q, r), side in occupied.items():
        col, row = Hex(q, r).axial_to_offset()
        desired[(col, row)] = side
    for (q, r) in occupied_contested:
        col, row = Hex(q, r).axial_to_offset()
        desired[(col, row)] = "contested"

    cleaned = {}
    for key, value in desired.items():
        if value not in (HL, WS, "contested"):
            continue
        if baseline.get(key) == value:
            continue
        cleaned[key] = value

    return cleaned
