from dataclasses import dataclass
import heapq
from typing import List, Tuple

from src.content.constants import NEUTRAL
from src.content.specs import LocType, UnitType
from src.game.map import Hex


@dataclass
class BoardActionResult:
    handled: bool
    messages: List[str]
    force_sync: bool


@dataclass
class MovementRangeResult:
    reachable_coords: List[Tuple[int, int]]
    neutral_warning_coords: List[Tuple[int, int]]


class MovementService:
    def __init__(self, game_state):
        self.game_state = game_state

    def get_reachable_hexes(self, units):
        """
        Returns reachable hexes plus neutral-border warnings for UI highlighting.
        """
        if not units:
            return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])

        start_hex, min_mp = self._get_stack_start_and_min_mp(units)
        if not start_hex or min_mp <= 0:
            return MovementRangeResult(reachable_coords=[], neutral_warning_coords=[])

        if self._is_neutral_hex(start_hex):
            reachable_hexes = self.game_state.map.get_reachable_hexes(units)
            return MovementRangeResult(
                reachable_coords=[h.axial_to_offset() for h in reachable_hexes],
                neutral_warning_coords=[]
            )

        return self._get_neutral_limited_range(units, start_hex, min_mp)

    def move_units_to_hex(self, units, target_hex):
        if not units:
            return []

        moved = []
        for unit in units:
            self.game_state.move_unit(unit, target_hex)
            moved.append(unit)
        return moved

    def _get_stack_start_and_min_mp(self, units):
        start_hex = None
        min_mp = 999

        for unit in units:
            if not getattr(unit, 'is_on_map', True):
                continue
            if hasattr(unit, 'position') and unit.position:
                col, row = unit.position
                h = Hex.offset_to_axial(col, row)
                if start_hex is None:
                    start_hex = h
                elif start_hex != h:
                    return None, 0

            m = unit.movement
            min_mp = min(min_mp, m)

        return start_hex, min_mp

    def _is_neutral_hex(self, hex_obj):
        col, row = hex_obj.axial_to_offset()
        country = self.game_state.get_country_by_hex(col, row)
        return bool(country and country.allegiance == NEUTRAL)

    def _get_neutral_limited_range(self, units, start_hex, min_mp):
        frontier = []
        heapq.heappush(frontier, (0, start_hex, False))
        cost_so_far = {(start_hex, False): 0}

        reachable_hexes = []
        warning_hexes = []

        while frontier:
            current_cost, current_hex, entered_neutral = heapq.heappop(frontier)

            if current_cost > min_mp:
                continue

            if current_cost > cost_so_far.get((current_hex, entered_neutral), float('inf')):
                continue

            if current_hex != start_hex:
                if self.game_state.map.can_stack_move_to(units, current_hex):
                    if self._is_neutral_hex(current_hex):
                        warning_hexes.append(current_hex)
                    else:
                        reachable_hexes.append(current_hex)

            if entered_neutral:
                continue

            for next_hex in current_hex.neighbors():
                # 1. Bounds check
                c, r = next_hex.axial_to_offset()
                if not (0 <= c < self.game_state.map.width and 0 <= r < self.game_state.map.height):
                    continue

                stack_cost = 0
                possible = True

                for unit in units:
                    # Check 1: Is hex occupied by enemy?
                    if self.game_state.map.has_enemy_army(next_hex, unit.allegiance):
                        possible = False
                        break

                    # Check 2: Sea Barrier
                    if unit.unit_type != UnitType.WING:
                        hexside = self.game_state.map.get_hexside(current_hex, next_hex)
                        if hexside == "sea":
                            possible = False
                            break

                    # Check 3: ZOC (Rule 5)
                    is_exempt = unit.unit_type in (UnitType.CAVALRY, UnitType.WING) or (hasattr(unit, 'is_leader') and unit.is_leader())
                    if not is_exempt:
                        if self.game_state.map.is_adjacent_to_enemy(current_hex, unit) and self.game_state.map.is_adjacent_to_enemy(next_hex, unit):
                            possible = False
                            break

                    # Check 4: Movement Cost
                    cost = self.game_state.map.get_movement_cost(unit, current_hex, next_hex)
                    if cost == float('inf') or cost is None:
                        possible = False
                        break

                    stack_cost = max(stack_cost, cost)

                if not possible:
                    continue

                new_cost = current_cost + stack_cost
                if new_cost <= min_mp:
                    next_entered_neutral = self._is_neutral_hex(next_hex)
                    key = (next_hex, next_entered_neutral)
                    if next_hex == start_hex:
                        continue
                    if key not in cost_so_far or new_cost < cost_so_far[key]:
                        cost_so_far[key] = new_cost
                        heapq.heappush(frontier, (new_cost, next_hex, next_entered_neutral))

        return MovementRangeResult(
            reachable_coords=[h.axial_to_offset() for h in reachable_hexes],
            neutral_warning_coords=[h.axial_to_offset() for h in warning_hexes]
        )

    def handle_board_action(self, selected_units):
        if not selected_units:
            return BoardActionResult(handled=False, messages=[], force_sync=False)

        messages = []

        # Separate fleets, armies, leaders
        fleets = [u for u in selected_units if u.unit_type == UnitType.FLEET or getattr(u, 'passengers', None) is not None]
        armies = [u for u in selected_units if u.is_army()]
        leaders = [u for u in selected_units if u.is_leader()]

        # If selection includes transported units, unboard them (only if carrier is in coastal hex)
        transported = [u for u in selected_units if getattr(u, 'transport_host', None) is not None]
        if transported:
            for u in transported:
                carrier = u.transport_host
                if not carrier or not carrier.position:
                    messages.append(f"Cannot unboard {u.id}: carrier missing position")
                    continue
                carrier_hex = Hex.offset_to_axial(*carrier.position)
                if carrier.unit_type == UnitType.WING:
                    if not self.game_state.map.can_unit_land_on_hex(u, carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: destination terrain invalid for passenger")
                        continue
                else:
                    # Check carrier hex is coastal
                    if not self.game_state.map.is_coastal(carrier_hex):
                        messages.append(f"Cannot unboard {u.id}: carrier not in coastal hex")
                        continue
                success = self.game_state.unboard_unit(u)
                if not success:
                    messages.append(f"Failed to unboard {u.id} due to stacking or location.")
            return BoardActionResult(handled=True, messages=messages, force_sync=True)

        # Unboarding variant: Because transported units cannot be selected (they're removed from the spatial map),
        # we detect carriers (fleets/wings/citadels) among the selection that have passengers and attempt to
        # unboard their passengers if the carrier is in a coastal hex or in a port.
        carriers_with_passengers = [u for u in selected_units if getattr(u, 'passengers', None) and len(u.passengers) > 0]
        if carriers_with_passengers:
            for carrier in carriers_with_passengers:
                if not carrier.position:
                    messages.append(f"Carrier {carrier.id} has no position, skipping unboard.")
                    continue
                carrier_hex = Hex.offset_to_axial(*carrier.position)
                if carrier.unit_type == UnitType.WING:
                    for p in carrier.passengers[:]:
                        if not self.game_state.map.can_unit_land_on_hex(p, carrier_hex):
                            messages.append(f"Cannot unboard {p.id} from {carrier.id}: destination terrain invalid")
                            continue
                        ok = self.game_state.unboard_unit(p)
                        if not ok:
                            messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")
                    continue
                is_coastal = self.game_state.map.is_coastal(carrier_hex)
                loc = self.game_state.map.get_location(carrier_hex)
                is_port = False
                if loc and isinstance(loc, dict):
                    is_port = (loc.get('type') == LocType.PORT.value)

                if not (is_coastal or is_port):
                    messages.append(f"Carrier {carrier.id} not in coastal hex or port, cannot unboard.")
                    continue

                # Unboard all passengers (copy list since unboard_unit mutates passengers)
                for p in carrier.passengers[:]:
                    ok = self.game_state.unboard_unit(p)
                    if not ok:
                        messages.append(f"Failed to unboard {p.id} from {carrier.id} (stacking or other).")

                # Movement restriction: if carrier is in a coastal land hex (coastal but NOT port), it cannot move further this Turn
                if is_coastal and not is_port:
                    # Ensure movement_points exists
                    carrier.movement_points = 0

            return BoardActionResult(handled=True, messages=messages, force_sync=True)

        # Otherwise attempt boarding
        if not fleets:
            messages.append("No fleet selected to board units into.")
            return BoardActionResult(handled=True, messages=messages, force_sync=False)

        # Algorithm: 1) Try to load every ground army into one selected fleet (one per fleet). Leaders load into same ships.
        # If there are more armies than fleets, remaining armies are not boarded.
        target_fleets = fleets[:]
        fi = 0
        for army in armies:
            if fi >= len(target_fleets):
                messages.append(f"No more fleets to board army {army.id}.")
                break
            fleet = target_fleets[fi]
            if self.game_state.board_unit(fleet, army):
                messages.append(f"Boarded army {army.id} onto {fleet.id}")
            else:
                messages.append(f"Failed to board army {army.id} onto {fleet.id}")
            fi += 1

        # Load leaders into the first fleet selected (if any)
        if leaders and fleets:
            primary = fleets[0]
            for l in leaders:
                if self.game_state.board_unit(primary, l):
                    messages.append(f"Boarded leader {l.id} onto {primary.id}")
                else:
                    messages.append(f"Failed to board leader {l.id} onto {primary.id}")

        return BoardActionResult(handled=True, messages=messages, force_sync=True)
