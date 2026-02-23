from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import UnitType, UnitState
from src.game.map import Hex


class BaselineAIPlayer:
    AI_MAX_MOVE_EVAL = 80
    AI_MAX_COMBAT_EVAL = 40
    AI_MOVE_TOPK_PER_STACK = 8
    AI_MOVE_EXEC_THRESHOLD = 20
    AI_COMBAT_EXEC_THRESHOLD = 0

    def __init__(self, game_state, movement_service, diplomacy_service):
        self.game_state = game_state
        self.movement_service = movement_service
        self.diplomacy_service = diplomacy_service

    # ---------- Deployment ----------
    def deploy_all_ready_units(self, side: str, allow_territory_wide: bool = False, country_filter: str | None = None) -> int:
        deployed = 0
        ready_units = [
            u for u in self.game_state.units
            if getattr(u, "allegiance", None) == side
            and getattr(u, "status", None) == UnitState.READY
            and not getattr(u, "is_on_map", False)
        ]
        if country_filter:
            ready_units = [u for u in ready_units if getattr(u, "land", None) == country_filter]

        ready_units.sort(key=lambda u: (str(getattr(u, "id", "")), int(getattr(u, "ordinal", 1))))

        objective_hexes = self._objective_hexes_for_side(side)
        for unit in ready_units:
            valid = self.game_state.get_valid_deployment_hexes(unit, allow_territory_wide=allow_territory_wide)
            if not valid:
                continue
            best = max(
                valid,
                key=lambda c: self._score_deployment_hex(unit, c, objective_hexes),
            )
            result = self.game_state.deployment_service.deploy_unit(
                unit,
                Hex.offset_to_axial(best[0], best[1]),
                invasion_deployment_active=False,
            )
            if result.success:
                deployed += 1
        return deployed

    # ---------- Activation ----------
    def perform_activation(self, side: str) -> tuple[bool, str | None]:
        neutrals = [
            c for c in self.game_state.countries.values()
            if getattr(c, "allegiance", None) == NEUTRAL
        ]
        if not neutrals:
            return False, None

        best = None
        best_score = float("-inf")
        for country in neutrals[:10]:
            attempt = self.diplomacy_service.build_activation_attempt(country.id)
            if not attempt:
                continue
            unit_count = sum(1 for u in self.game_state.units if getattr(u, "land", None) == country.id)
            score = (
                int(getattr(attempt, "target_rating", 0) or 0) * 20
                + unit_count * 12
                + self._country_objective_relevance(side, country.id) * 50
            )
            if score > best_score:
                best_score = score
                best = country

        if not best:
            return False, None

        attempt = self.diplomacy_service.build_activation_attempt(best.id)
        if not attempt:
            return False, None
        bonus = int(getattr(attempt, "event_activation_bonus", 0) or 0)
        roll = self.diplomacy_service.roll_activation(attempt.target_rating, roll_bonus=bonus)
        if not roll.success:
            return False, best.id

        self.diplomacy_service.activate_country(best.id, side)
        deployed = self.deploy_all_ready_units(side, allow_territory_wide=True, country_filter=best.id)
        print(f"AI activation success: {best.id}. Deployed units: {deployed}")
        return True, best.id

    # ---------- Movement ----------
    def execute_best_movement(self, side: str) -> bool:
        stacks = self._build_movable_stacks(side)
        if not stacks:
            return False

        objective_hexes = self._objective_hexes_for_side(side)
        candidates = []
        eval_count = 0

        for stack in stacks:
            range_result = self.movement_service.get_reachable_hexes(stack)
            if not range_result.reachable_coords:
                continue
            scored = []
            for coords in range_result.reachable_coords:
                if eval_count >= self.AI_MAX_MOVE_EVAL:
                    break
                eval_count += 1
                score = self._score_move_target(stack, coords, objective_hexes, side)
                scored.append((score, stack, coords))
            scored.sort(key=lambda item: item[0], reverse=True)
            candidates.extend(scored[: self.AI_MOVE_TOPK_PER_STACK])
            if eval_count >= self.AI_MAX_MOVE_EVAL:
                break

        if not candidates:
            return False

        candidates.sort(key=lambda item: item[0], reverse=True)
        for score, stack, coords in candidates:
            if score < self.AI_MOVE_EXEC_THRESHOLD:
                return False
            target_hex = Hex.offset_to_axial(coords[0], coords[1])
            result = self.movement_service.move_units_to_hex(stack, target_hex)
            if not result.errors and result.moved:
                print(f"AI move score {score}: {len(result.moved)} unit(s) to {coords}")
                return True
        return False

    # ---------- Combat ----------
    def execute_best_combat(self, side: str) -> bool:
        candidates = self._combat_candidates(side)
        if not candidates:
            return False

        candidates.sort(key=lambda item: item["score"], reverse=True)
        for candidate in candidates:
            if candidate["score"] < self.AI_COMBAT_EXEC_THRESHOLD:
                return False
            attackers = candidate["attackers"]
            target_hex = candidate["target_hex"]
            resolution = self.game_state.resolve_combat(attackers, target_hex)
            for u in attackers:
                u.attacked_this_turn = True
            self._resolve_ai_leader_escapes(resolution)
            if resolution and resolution.get("advance_available"):
                try:
                    self.game_state.advance_after_combat(attackers, target_hex)
                except Exception:
                    pass
            print(
                f"AI combat score {candidate['score']}: "
                f"{len(attackers)} attacker(s) vs {target_hex.axial_to_offset()}"
            )
            return True
        return False

    # ---------- Evaluation helpers ----------
    def _build_movable_stacks(self, side: str):
        by_hex = defaultdict(list)
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != side:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            if getattr(unit, "position", None) is None or unit.position[0] is None:
                continue
            if int(getattr(unit, "movement_points", getattr(unit, "movement", 0)) or 0) <= 0:
                continue
            by_hex[tuple(unit.position)].append(unit)

        stacks = []
        for units in by_hex.values():
            ground = [u for u in units if getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)]
            air = [u for u in units if getattr(u, "unit_type", None) in (UnitType.WING, UnitType.CITADEL)]
            fleet = [u for u in units if getattr(u, "unit_type", None) == UnitType.FLEET]
            if ground:
                stacks.append(sorted(ground, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
            if air:
                stacks.append(sorted(air, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
            if fleet:
                stacks.append(sorted(fleet, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
        return stacks

    def _score_move_target(self, stack, target_coords, objective_hexes: set[tuple[int, int]], side: str) -> int:
        target_hex = Hex.offset_to_axial(target_coords[0], target_coords[1])
        start = stack[0].position if stack and getattr(stack[0], "position", None) else target_coords

        start_dist = self._min_distance_to_objectives(start, objective_hexes)
        end_dist = self._min_distance_to_objectives(target_coords, objective_hexes)
        dist_gain = (start_dist - end_dist) if start_dist < 999 else 0

        enemy_adj = self._adjacent_enemy_count(target_hex, side)
        friendly_adj = self._adjacent_friendly_count(target_hex, side)
        enemy_here = len(
            [
                u
                for u in self.game_state.get_units_at(target_hex)
                if getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
            ]
        )

        risk = 0
        if enemy_adj > 0 and friendly_adj == 0:
            risk -= 140
        if enemy_adj >= 3:
            risk -= 80

        return int(dist_gain * 20 + enemy_here * 60 + enemy_adj * 25 + friendly_adj * 8 + risk)

    def _score_deployment_hex(self, unit, coords: tuple[int, int], objective_hexes: set[tuple[int, int]]) -> int:
        target_hex = Hex.offset_to_axial(coords[0], coords[1])
        side = getattr(unit, "allegiance", None)
        dist = self._min_distance_to_objectives(coords, objective_hexes)
        friendly_adj = self._adjacent_friendly_count(target_hex, side)
        enemy_adj = self._adjacent_enemy_count(target_hex, side)
        return int((0 if dist >= 999 else -dist * 12) + friendly_adj * 10 - enemy_adj * 14)

    def _combat_candidates(self, side: str):
        candidates = []
        evaluated = 0
        by_hex = self.game_state.map.unit_map

        for (q, r), units in list(by_hex.items()):
            if evaluated >= self.AI_MAX_COMBAT_EVAL:
                break
            source_hex = Hex(q, r)
            source_units = [
                u for u in units
                if getattr(u, "allegiance", None) == side
                and getattr(u, "is_on_map", False)
                and not getattr(u, "attacked_this_turn", False)
                and getattr(u, "transport_host", None) is None
            ]
            if not source_units:
                continue

            land_attackers = [
                u for u in source_units
                if self.game_state._is_combat_stack_unit(u) and getattr(u, "unit_type", None) != UnitType.FLEET
            ]
            fleet_attackers = [u for u in source_units if getattr(u, "unit_type", None) == UnitType.FLEET]

            for target_hex in source_hex.neighbors():
                defenders = [
                    u for u in self.game_state.get_units_at(target_hex)
                    if getattr(u, "is_on_map", False)
                    and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
                ]
                if not defenders:
                    continue

                if land_attackers:
                    score = self._score_combat(land_attackers, defenders, target_hex, side)
                    candidates.append({"score": score, "attackers": list(land_attackers), "target_hex": target_hex})
                    evaluated += 1
                    if evaluated >= self.AI_MAX_COMBAT_EVAL:
                        break

                naval_ready = [f for f in fleet_attackers if self.game_state.can_fleet_attack_hex(f, target_hex)]
                if naval_ready:
                    score = self._score_combat(naval_ready, defenders, target_hex, side)
                    candidates.append({"score": score, "attackers": list(naval_ready), "target_hex": target_hex})
                    evaluated += 1
                    if evaluated >= self.AI_MAX_COMBAT_EVAL:
                        break

        return candidates

    def _score_combat(self, attackers, defenders, target_hex: Hex, side: str) -> int:
        att = sum(int(getattr(u, "combat_rating", 0) or 0) for u in attackers)
        deff = sum(int(getattr(u, "combat_rating", 0) or 0) for u in defenders)
        material = (att - deff) * 15
        objective_bonus = 0
        if target_hex.axial_to_offset() in self._objective_hexes_for_side(side):
            objective_bonus += 220
        enemy_side = self.game_state.get_enemy_allegiance(side)
        if target_hex.axial_to_offset() in self._objective_hexes_for_side(enemy_side):
            objective_bonus += 260
        return material + objective_bonus

    def _resolve_ai_leader_escapes(self, resolution: dict[str, Any] | None):
        if not resolution:
            return
        requests = resolution.get("leader_escape_requests") or []
        for req in requests:
            leader = getattr(req, "leader", None)
            options = getattr(req, "options", None) or []
            if not leader or not options:
                continue
            destination = options[0]
            try:
                self.game_state.move_unit(leader, destination)
            except Exception:
                continue

    def _objective_hexes_for_side(self, side: str) -> set[tuple[int, int]]:
        out = set()
        vc = getattr(self.game_state.scenario_spec, "victory_conditions", {}) or {}
        side_vc = vc.get(side, {}) or {}
        self._collect_objective_hexes(side_vc.get("major"), out)
        minor = side_vc.get("minor")
        if isinstance(minor, dict) and "conditions" in minor:
            for item in minor.get("conditions", []) or []:
                node = item.get("when") if isinstance(item, dict) and "when" in item else item
                self._collect_objective_hexes(node, out)
        else:
            self._collect_objective_hexes(minor, out)
        return out

    def _collect_objective_hexes(self, node: Any, out: set[tuple[int, int]]):
        if node is None:
            return
        if isinstance(node, list):
            for child in node:
                self._collect_objective_hexes(child, out)
            return
        if not isinstance(node, dict):
            return
        if "all" in node:
            for child in node.get("all", []) or []:
                self._collect_objective_hexes(child, out)
            return
        if "any" in node:
            for child in node.get("any", []) or []:
                self._collect_objective_hexes(child, out)
            return

        ntype = str(node.get("type", ""))
        if ntype in {"capture_location", "prevent_location_captured"}:
            loc_id = str(node.get("location", "")).strip().lower()
            for country in self.game_state.countries.values():
                loc = country.locations.get(loc_id)
                if loc and loc.coords:
                    out.add(tuple(loc.coords))
        elif ntype in {"conquer_country", "prevent_country_conquered", "ally_country", "prevent_country_control"}:
            cid = str(node.get("country", "")).strip().lower()
            country = self.game_state.countries.get(cid)
            if country:
                for loc in country.locations.values():
                    if loc.coords:
                        out.add(tuple(loc.coords))
        elif ntype == "escape_unit_score":
            for item in node.get("hexes", []) or node.get("escape_hexes", []) or []:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    out.add((int(item[0]), int(item[1])))

    def _country_objective_relevance(self, side: str, country_id: str) -> int:
        objectives = self._objective_hexes_for_side(side)
        country = self.game_state.countries.get(country_id)
        if not country:
            return 0
        score = 0
        for loc in country.locations.values():
            if loc.coords and tuple(loc.coords) in objectives:
                score += 1
        return score

    @staticmethod
    def _distance(a: tuple[int, int], b: tuple[int, int]) -> int:
        ah = Hex.offset_to_axial(a[0], a[1])
        bh = Hex.offset_to_axial(b[0], b[1])
        return int(ah.distance_to(bh))

    def _min_distance_to_objectives(self, src: tuple[int, int], objectives: set[tuple[int, int]]) -> int:
        if not objectives:
            return 999
        return min(self._distance(src, dst) for dst in objectives)

    def _adjacent_enemy_count(self, hex_obj: Hex, side: str) -> int:
        count = 0
        for n in hex_obj.neighbors():
            units = self.game_state.map.get_units_in_hex(n.q, n.r)
            if any(getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) not in (side, NEUTRAL, None) for u in units):
                count += 1
        return count

    def _adjacent_friendly_count(self, hex_obj: Hex, side: str) -> int:
        count = 0
        for n in hex_obj.neighbors():
            units = self.game_state.map.get_units_in_hex(n.q, n.r)
            if any(getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) == side for u in units):
                count += 1
        return count
