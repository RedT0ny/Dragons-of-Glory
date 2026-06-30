from collections import deque

from src.content.constants import NEUTRAL
from src.content.specs import HexsideType, TerrainType, UnitState
from src.game.map import Hex


class SupplyService:
    """Encapsulates supply tracing and attrition logic (Rule 12 advanced supply)."""

    def __init__(self, game_state):
        self.gs = game_state

    def resolve_supply_phase(self):
        """
        Rule 12 (advanced supply):
        - Only stacked ground armies (>1 in a hex) must trace supply.
        - If no legal path to any friendly location, one army in that stack goes to RESERVE.
        """
        supply_mode = str(getattr(self.gs, "supply", "standard")).strip().lower()
        if supply_mode != "advanced" or not self.gs.map:
            return []

        active = self.gs.active_player
        friendly_locations = {
            (q, r)
            for (q, r), loc in getattr(self.gs.map, "locations", {}).items()
            if getattr(loc, "occupier", None) == active
        }

        losses = []
        for (q, r), units in list(self.gs.map.unit_map.items()):
            stack_armies = [
                u for u in units
                if u.is_on_map
                and u.allegiance == active
                and u.is_army()
            ]
            if len(stack_armies) <= 1:
                continue

            stack_hex = Hex(q, r)
            if self._can_trace_supply_line(stack_hex, active, stack_armies[0], friendly_locations):
                continue

            casualty = self._select_supply_attrition_unit(stack_armies)
            if casualty is None:
                continue
            if getattr(casualty, "is_on_map", False):
                self.gs.map.remove_unit_from_spatial_map(casualty)
            casualty.status = UnitState.RESERVE
            casualty.position = (None, None)
            losses.append(casualty)

        self.gs.finalize_board_state_change()
        return losses

    def _can_trace_supply_line(self, start_hex, allegiance, sample_unit, friendly_locations):
        if not friendly_locations:
            return False

        frontier = deque([start_hex])
        visited = {(start_hex.q, start_hex.r)}

        while frontier:
            current = frontier.popleft()
            if (current.q, current.r) in friendly_locations:
                return True

            for neighbor in current.neighbors():
                nk = (neighbor.q, neighbor.r)
                if nk in visited:
                    continue
                if not self.is_valid_supply_step(current, neighbor, allegiance, sample_unit):
                    continue
                visited.add(nk)
                frontier.append(neighbor)

        return False

    def is_valid_supply_step(self, from_hex, to_hex, allegiance, sample_unit):
        col, row = to_hex.axial_to_offset()
        if not (0 <= col < self.gs.map.width and 0 <= row < self.gs.map.height):
            return False

        terrain = self.gs.map.get_terrain(to_hex)
        if terrain in (TerrainType.OCEAN, TerrainType.MAELSTROM, TerrainType.DESERT, TerrainType.SWAMP):
            return False

        # Neutral countries block supply
        country = self.gs.get_country_by_hex(col, row)
        if country and country.allegiance == NEUTRAL:
            return False

        hexside = self.gs.map.get_effective_hexside(from_hex, to_hex)
        if hexside in {HexsideType.MOUNTAIN, HexsideType.DEEP_RIVER, HexsideType.SEA}:
            return False

        if self.gs.map.has_enemy_army(to_hex, allegiance):
            return False

        # Enemy ZOC blocks trace unless the hex has a friendly counter.
        if self.gs.map.is_adjacent_to_enemy(to_hex, sample_unit) and not self.gs.map.has_friendly_counter(to_hex, allegiance):
            return False

        return True

    @staticmethod
    def _select_supply_attrition_unit(stack_armies):
        depleted = [u for u in stack_armies if u.status.name == "DEPLETED"]
        if depleted:
            return min(depleted, key=lambda u: (int(u.combat_rating), str(u.id), int(u.ordinal)))
        active = [u for u in stack_armies if u.status.name == "ACTIVE"]
        if active:
            return min(active, key=lambda u: (int(u.combat_rating), str(u.id), int(u.ordinal)))
        return min(
            stack_armies,
            key=lambda u: (
                0 if u.is_on_map else 1,
                int(u.combat_rating),
                str(u.id),
                int(u.ordinal),
            ),
        ) if stack_armies else None
