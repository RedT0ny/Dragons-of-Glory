import random
from dataclasses import dataclass
from typing import Iterable, List

from src.content.specs import LocType, UnitState
from src.content.tools import TextFormatter


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
            if leader.status == UnitState.DESTROYED:
                continue
            if getattr(check, "require_leader_on_map", True):
                if not leader.is_on_map or not getattr(leader, "position", None):
                    continue
            if getattr(check, "require_prior_combat_stack", False) and not getattr(check, "prior_had_combat_stack", False):
                continue
            if getattr(check, "skip_if_allied_combat_present", True) and self._has_allied_combat_stack(leader, origin_hex):
                continue

            if getattr(check, "roll_required", True):
                roll = self._roll_d6()
                if roll <= 3:
                    self.game_state.damage_unit(leader, mode="destroy")
                    destroyed.append(leader)
                    continue

            options = self._get_nearest_friendly_stacks(
                leader=leader,
                origin_hex=origin_hex,
                allow_fleet=getattr(check, "allow_fleet_destinations", False),
            )
            if not options:
                self.game_state.damage_unit(leader, mode="destroy")
                destroyed.append(leader)
                continue

            if getattr(check, "auto_place_on_success", False):
                destination = self.choose_escape_destination(leader, options)
                if destination and self._place_leader(leader, destination):
                    continue
                self.game_state.damage_unit(leader, mode="destroy")
                destroyed.append(leader)
                continue

            if auto_resolve_ai and self._is_ai_allegiance(getattr(leader, "allegiance", None)):
                destination = self.choose_escape_destination(leader, options)
                if destination and self._place_leader(leader, destination):
                    continue
                self.game_state.damage_unit(leader, mode="destroy")
                destroyed.append(leader)
                continue

            requests.append(LeaderEscapeRequest(leader=leader, options=options))

        if destroyed:
            self.game_state.combat_service.cleanup_destroyed_units(destroyed)

        return requests

    def complete_escapes(self, requests, prompt_chooser=None, note="after combat"):
        """Resolve pending leader escape requests through the single shared entry point.

        Both combat (``CombatClickHandler``) and movement-phase interceptions
        (``InterceptionService``) route their ``LeaderEscapeRequest`` lists here.
        Each request's ``options`` are the nearest friendly stacks (all tied at
        the same minimum distance): a single option is placed directly; when
        several friendly stacks are tied, a human player picks through
        ``prompt_chooser`` (a modal destination dialog by default) and AI
        leaders are auto-picked. Cancelling falls back to
        ``choose_escape_destination``; a leader with no destination is
        destroyed rather than left stranded.
        """
        requests = list(requests or [])
        if not requests:
            return
        destroyed = []
        for request in requests:
            leader = getattr(request, "leader", None)
            if not leader:
                continue
            options = list(getattr(request, "options", []) or [])
            destination = None
            if options:
                if len(options) == 1:
                    destination = options[0]
                elif self._is_ai_allegiance(getattr(leader, "allegiance", None)):
                    destination = self.choose_escape_destination(leader, options)
                else:
                    chooser = prompt_chooser or self._prompt_human_escape_destination
                    destination = chooser(leader, options)
                if destination is None:
                    destination = self.choose_escape_destination(leader, options)
            if destination is None:
                self.game_state.damage_unit(leader, mode="destroy")
                destroyed.append(leader)
                print(
                    f"Leader {TextFormatter.format_unit_log_string(leader)} destroyed: "
                    "no escape destination available."
                )
                continue
            if hasattr(leader, "_tactical_rating_override"):
                leader._tactical_rating_override = 0
            self._place_leader(leader, destination)
            print(
                f"Leader {TextFormatter.format_unit_log_string(leader)} escaped to "
                f"{destination.axial_to_offset()} {note}."
            )
        if destroyed:
            self.game_state.combat_service.cleanup_destroyed_units(destroyed)
        self.game_state.finalize_board_state_change()

    def _prompt_human_escape_destination(self, leader, options):
        """Let a human player pick the escape destination for a leader."""
        from PySide6.QtWidgets import QApplication, QInputDialog

        option_labels = [self._describe_escape_option(hex_obj) for hex_obj in options]
        app = QApplication.instance()
        parent = app.activeWindow() if app else None
        choice, ok = QInputDialog.getItem(
            parent,
            "Leader Escape",
            f"Select a destination for {TextFormatter.format_unit_log_string(leader)} to escape to:",
            option_labels,
            0,
            False,
        )
        if not ok or not choice:
            return None
        try:
            return options[option_labels.index(choice)]
        except ValueError:
            return None

    def _describe_escape_option(self, hex_obj):
        col, row = hex_obj.axial_to_offset()
        units = self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
        names = TextFormatter.format_units([u for u in units if u.is_on_map])
        return f"({col}, {row}) - {names}"

    def choose_escape_destination(self, leader, options):
        """
        Chooses leader escape destination.

        Given a list of hex options, prioritize:
        1. those with friendly combat stacks,
        2. then locations,
        3. then by highest total combat rating of friendly units.
        4. Break ties randomly.
        """
        if not options:
            return None

        def stack_score(hex_obj):
            units = self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
            return sum(
                int(unit.combat_rating)
                for unit in units
                if unit.is_on_map
                and unit.allegiance == leader.allegiance
                and unit.is_combat_unit()
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
        self.game_state.movement_service.relocate_unit_on_board(
            leader,
            target_hex,
            clear_escaped=False,
        )
        return True

    def _has_allied_combat_stack(self, leader, origin_hex):
        units_in_hex = self.game_state.map.get_units_in_hex(origin_hex.q, origin_hex.r)
        return any(
            unit.allegiance == leader.allegiance
            and unit.is_control_unit()
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
            if unit.allegiance != leader.allegiance:
                continue
            if not unit.is_on_map:
                continue
            if allow_fleet and unit.is_fleet():
                return True
            if unit.is_control_unit():
                return True
        return False

    def _is_ai_allegiance(self, allegiance):
        if not allegiance:
            return False
        player = self.game_state.players.get(allegiance) if hasattr(self.game_state, "players") else None
        return bool(player and getattr(player, "is_ai", False))
