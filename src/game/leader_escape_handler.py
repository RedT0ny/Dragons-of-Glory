import random
from dataclasses import dataclass
from typing import Iterable, List

from src.content.specs import LocType, UnitState, UnitType


@dataclass
class LeaderEscapeRequest:
    leader: object
    options: List[object]


@dataclass
class LeaderEscapeCheck:
    leader: object
    origin_hex: object
    allow_fleet_destinations: bool = False
    roll_required: bool = True
    require_prior_combat_stack: bool = False
    prior_had_combat_stack: bool = True
    skip_if_allied_combat_present: bool = True
    auto_place_on_success: bool = False
    require_leader_on_map: bool = True


class LeaderEscapeHandler:
    def __init__(self, game_state, roll_d6_fn=None):
        self.game_state = game_state
        self._roll_d6 = roll_d6_fn or (lambda: random.randint(1, 6))

    def handle_leader_escapes(self, checks: Iterable[LeaderEscapeCheck], auto_resolve_ai: bool = False):
        requests = []
        destroyed = []

        for check in checks:
            leader = getattr(check, "leader", None)
            origin_hex = getattr(check, "origin_hex", None)
            if not leader or not origin_hex:
                continue
            if getattr(leader, "status", None) == UnitState.DESTROYED:
                continue
            if getattr(check, "require_leader_on_map", True):
                if not getattr(leader, "is_on_map", False) or not getattr(leader, "position", None):
                    continue
            if getattr(check, "require_prior_combat_stack", False) and not getattr(check, "prior_had_combat_stack", False):
                continue
            if getattr(check, "skip_if_allied_combat_present", True) and self._has_allied_combat_stack(leader, origin_hex):
                continue

            if getattr(check, "roll_required", True):
                roll = self._roll_d6()
                if roll <= 3:
                    leader.destroy()
                    destroyed.append(leader)
                    continue

            options = self._get_nearest_friendly_stacks(
                leader=leader,
                origin_hex=origin_hex,
                allow_fleet=getattr(check, "allow_fleet_destinations", False),
            )
            if not options:
                leader.destroy()
                destroyed.append(leader)
                continue

            if getattr(check, "auto_place_on_success", False):
                destination = self.choose_escape_destination(leader, options)
                if destination and self._place_leader(leader, destination):
                    continue
                leader.destroy()
                destroyed.append(leader)
                continue

            if auto_resolve_ai and self._is_ai_allegiance(getattr(leader, "allegiance", None)):
                destination = self.choose_escape_destination(leader, options)
                if destination and self._place_leader(leader, destination):
                    continue
                leader.destroy()
                destroyed.append(leader)
                continue

            requests.append(LeaderEscapeRequest(leader=leader, options=options))

        if destroyed:
            self.game_state._cleanup_destroyed_units(destroyed)

        return requests

    def choose_escape_destination(self, leader, options):
        if not options:
            return None

        def stack_score(hex_obj):
            units = self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
            return sum(
                int(getattr(unit, "combat_rating", 0) or 0)
                for unit in units
                if getattr(unit, "is_on_map", False)
                and getattr(unit, "allegiance", None) == getattr(leader, "allegiance", None)
                and (
                    self._is_combat_stack_unit(unit)
                    or getattr(unit, "unit_type", None) == UnitType.FLEET
                )
            )

        def is_location(hex_obj):
            location = self.game_state.map.get_location(hex_obj)
            if not location:
                return False
            loc_type = getattr(location, "loc_type", None)
            if isinstance(loc_type, LocType):
                loc_type = loc_type.value
            return loc_type in {lt.value for lt in LocType}

        ranked = sorted(
            options,
            key=lambda h: (
                0 if is_location(h) else 1,
                -stack_score(h),
            ),
        )
        if not ranked:
            return None
        top = ranked[0]
        ties = [
            h for h in ranked
            if is_location(h) == is_location(top) and stack_score(h) == stack_score(top)
        ]
        return random.choice(ties)

    def _place_leader(self, leader, target_hex):
        if leader.status not in UnitState.on_map_states():
            leader.status = UnitState.ACTIVE
        leader.position = target_hex.axial_to_offset()
        self.game_state.map.add_unit_to_spatial_map(leader)
        return True

    def _has_allied_combat_stack(self, leader, origin_hex):
        units_in_hex = self.game_state.map.get_units_in_hex(origin_hex.q, origin_hex.r)
        return any(
            getattr(unit, "allegiance", None) == getattr(leader, "allegiance", None)
            and self._is_combat_stack_unit(unit)
            for unit in units_in_hex
        )

    def _get_nearest_friendly_stacks(self, leader, origin_hex, allow_fleet):
        candidates = []
        for (q, r), units in self.game_state.map.unit_map.items():
            if not units:
                continue
            if not self._hex_has_friendly_escape_stack(units, leader, allow_fleet):
                continue
            from src.game.map import Hex
            candidates.append(Hex(q, r))

        if not candidates:
            return []

        min_distance = min(origin_hex.distance_to(h) for h in candidates)
        return [h for h in candidates if origin_hex.distance_to(h) == min_distance]

    def _hex_has_friendly_escape_stack(self, units, leader, allow_fleet):
        for unit in units:
            if getattr(unit, "allegiance", None) != getattr(leader, "allegiance", None):
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if allow_fleet and getattr(unit, "unit_type", None) == UnitType.FLEET:
                return True
            if self._is_combat_stack_unit(unit):
                return True
        return False

    def _is_combat_stack_unit(self, unit):
        return bool(
            (hasattr(unit, "is_army") and unit.is_army())
            or getattr(unit, "unit_type", None) in (UnitType.INFANTRY, UnitType.CAVALRY, UnitType.WING, UnitType.CITADEL)
        )

    def _is_ai_allegiance(self, allegiance):
        if not allegiance:
            return False
        player = self.game_state.players.get(allegiance) if hasattr(self.game_state, "players") else None
        return bool(player and getattr(player, "is_ai", False))
