from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import UnitType, UnitState, LocType, TerrainType
from src.game.map import Hex
from src.game.combat_reporting import show_combat_result_popup


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
    def deploy_all_ready_units(
        self,
        side: str,
        allow_territory_wide: bool = False,
        country_filter: str | None = None,
        invasion_deployment_active: bool = False,
        invasion_deployment_allegiance: str | None = None,
        invasion_deployment_country_id: str | None = None,
    ) -> int:
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
            if valid:
                valid = [c for c in valid if not self._is_trapped_mountain_deploy(unit, c)]
            if not valid:
                continue
            best = max(
                valid,
                key=lambda c: self._score_deployment_hex(unit, c, objective_hexes),
            )
            result = self.game_state.deployment_service.deploy_unit(
                unit,
                Hex.offset_to_axial(best[0], best[1]),
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if result.success:
                deployed += 1
        return deployed

    # ---------- Replacements ----------
    def process_replacements(self, side: str) -> tuple[int, int]:
        """
        AI replacements flow:
        1. Conscript RESERVE pairs into READY/DESTROYED using existing game rules.
        2. Deploy all READY units available for this side.
        Returns: (conscriptions_applied, units_deployed)
        """
        conscriptions = self._apply_conscriptions(side)
        deployed = self.deploy_all_ready_units(side)
        return conscriptions, deployed

    def _apply_conscriptions(self, side: str) -> int:
        conscriptions = 0
        while True:
            reserve_units = [
                u for u in self.game_state.units
                if getattr(u, "allegiance", None) == side
                and getattr(u, "status", None) == UnitState.RESERVE
            ]
            if len(reserve_units) < 2:
                break

            groups = defaultdict(list)
            for unit in reserve_units:
                key = self.game_state.get_replacement_group_key(unit)
                groups[key].append(unit)

            pair_found = False
            for key in sorted(groups.keys(), key=lambda x: str(x)):
                units = groups[key]
                if len(units) < 2:
                    continue
                units = sorted(units, key=lambda u: self._conscription_sort_key(u), reverse=True)
                kept_unit = units[0]
                discarded_unit = units[1]
                if not self.game_state.can_conscript_pair(kept_unit, discarded_unit):
                    continue
                self.game_state.apply_conscription(kept_unit, discarded_unit)
                conscriptions += 1
                pair_found = True
                break

            if not pair_found:
                break
        return conscriptions

    @staticmethod
    def _conscription_sort_key(unit):
        return (
            int(getattr(unit, "combat_rating", 0) or 0),
            int(getattr(unit, "tactical_rating", 0) or 0),
            int(getattr(unit, "movement", 0) or 0),
            str(getattr(unit, "id", "")),
            -int(getattr(unit, "ordinal", 1)),
        )

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

    # ---------- Assets ----------
    def assign_assets(self, side: str) -> int:
        """
        Equip AI-owned unassigned equippable assets on best candidate units.
        Returns number of assignments made.
        """
        player = self.game_state.players.get(side)
        if not player:
            return 0

        assets = [
            a for a in getattr(player, "assets", {}).values()
            if getattr(a, "is_equippable", False)
            and getattr(a, "assigned_to", None) is None
        ]
        if not assets:
            return 0

        units = [
            u for u in self.game_state.units
            if getattr(u, "allegiance", None) == side
            and getattr(u, "is_on_map", False)
        ]
        if not units:
            return 0

        assigned = 0
        # Highest-impact artifacts first.
        assets.sort(key=lambda a: self._asset_priority(a), reverse=True)

        for asset in assets:
            candidates = [u for u in units if asset.can_equip(u)]
            if not candidates:
                continue

            if self._is_crown_of_power(asset):
                best = max(candidates, key=lambda u: self._score_crown_target(u, side))
            else:
                best = max(candidates, key=lambda u: self._score_asset_target(asset, u, side))

            asset.apply_to(best)
            if getattr(asset, "assigned_to", None) is best:
                assigned += 1

        return assigned

    @staticmethod
    def _is_crown_of_power(asset) -> bool:
        if getattr(asset, "id", None) == "crown_of_power":
            return True
        return bool(hasattr(asset, "has_other_bonus") and asset.has_other_bonus("emperor"))

    def _asset_priority(self, asset) -> int:
        if self._is_crown_of_power(asset):
            return 100
        if hasattr(asset, "has_other_bonus"):
            if asset.has_other_bonus("dragon_orb"):
                return 90
            if asset.has_other_bonus("revive"):
                return 85
            if asset.has_other_bonus("dragon_slayer"):
                return 80
            if asset.has_other_bonus("gnome_tech"):
                return 70
            if asset.has_other_bonus("armor"):
                return 65
            if asset.has_other_bonus("healing"):
                return 60
        return 50

    def _score_crown_target(self, unit, side: str) -> int:
        score = 0
        dragonflight = self._unit_dragonflight(unit)
        if dragonflight:
            dragons_alive = self._count_dragons_for_flight(side, dragonflight)
            sibling_highlords = self._count_other_highlords_for_flight(side, dragonflight, exclude=unit)
            if dragons_alive == 0:
                score += 10000
            elif dragons_alive == 1 and sibling_highlords > 0:
                score += 9000
            elif sibling_highlords > 0:
                score += 8000
            else:
                score += 7000
            score += max(0, 10 - dragons_alive) * 20
            score += sibling_highlords * 120
        else:
            score += 6000

        score += self._survival_score(unit)
        score += self._frontline_score(unit, side)
        score += int(getattr(unit, "tactical_rating", 0) or 0) * 10
        return score

    def _score_asset_target(self, asset, unit, side: str) -> int:
        score = 0
        if getattr(unit, "unit_type", None) in (UnitType.HIGHLORD, UnitType.GENERAL, UnitType.ADMIRAL, UnitType.WIZARD):
            score += 160
        elif hasattr(unit, "is_army") and unit.is_army():
            score += 120
        elif getattr(unit, "unit_type", None) == UnitType.WING:
            score += 90
        elif getattr(unit, "unit_type", None) == UnitType.FLEET:
            score += 70

        if hasattr(asset, "has_other_bonus"):
            if asset.has_other_bonus("dragon_orb"):
                score += 400 if getattr(unit, "is_leader", lambda: False)() else -500
                score += self._nearby_enemy_dragons_or_draconians(unit, side) * 80
            elif asset.has_other_bonus("dragon_slayer"):
                score += self._nearby_enemy_dragons_or_draconians(unit, side) * 70
                if hasattr(unit, "is_army") and unit.is_army():
                    score += 150
            elif asset.has_other_bonus("armor"):
                score += self._frontline_score(unit, side) * 2
                score += self._survival_score(unit) // 2
            elif asset.has_other_bonus("healing"):
                score += 180 if hasattr(unit, "is_army") and unit.is_army() else 60
                if getattr(unit, "status", None) == UnitState.DEPLETED:
                    score += 180
            elif asset.has_other_bonus("revive"):
                score += 220 if getattr(unit, "is_leader", lambda: False)() else 0
                score += self._survival_score(unit)
            elif asset.has_other_bonus("gnome_tech"):
                score += 220 if hasattr(unit, "is_army") and unit.is_army() else 0
                score += self._frontline_score(unit, side) * 2

        bonus = getattr(asset, "bonus", {})
        if isinstance(bonus, dict):
            score += int(bonus.get("tactical_rating", 0) or 0) * 45
            # Avoid overvaluing multiplicative strings, but keep some weight.
            combat_bonus = bonus.get("combat_rating", bonus.get("combat", 0))
            if isinstance(combat_bonus, (int, float)):
                score += int(combat_bonus) * 40
            elif isinstance(combat_bonus, str):
                score += 35
            if "diplomacy" in bonus and self.game_state.has_neutral_countries():
                score += 60 if getattr(unit, "is_leader", lambda: False)() else 20

        score += self._survival_score(unit)
        score += self._frontline_score(unit, side)
        return score

    @staticmethod
    def _unit_dragonflight(unit) -> str | None:
        spec = getattr(unit, "spec", None)
        value = getattr(spec, "dragonflight", None) if spec else None
        if value:
            return str(value).strip().lower()
        return None

    def _count_dragons_for_flight(self, side: str, dragonflight: str) -> int:
        return sum(
            1
            for u in self.game_state.units
            if getattr(u, "allegiance", None) == side
            and getattr(u, "is_on_map", False)
            and getattr(u, "unit_type", None) == UnitType.WING
            and str(getattr(getattr(u, "spec", None), "dragonflight", "")).strip().lower() == dragonflight
        )

    def _count_other_highlords_for_flight(self, side: str, dragonflight: str, exclude) -> int:
        return sum(
            1
            for u in self.game_state.units
            if u is not exclude
            and getattr(u, "allegiance", None) == side
            and getattr(u, "is_on_map", False)
            and getattr(u, "unit_type", None) == UnitType.HIGHLORD
            and self._unit_dragonflight(u) == dragonflight
        )

    def _nearby_enemy_dragons_or_draconians(self, unit, side: str) -> int:
        if not getattr(unit, "position", None) or unit.position[0] is None:
            return 0
        center = Hex.offset_to_axial(unit.position[0], unit.position[1])
        count = 0
        for hex_obj in [center] + list(center.neighbors()):
            enemies = [
                u for u in self.game_state.get_units_at(hex_obj)
                if getattr(u, "is_on_map", False)
                and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
            ]
            for enemy in enemies:
                if getattr(enemy, "unit_type", None) == UnitType.WING:
                    count += 1
                else:
                    enemy_race = getattr(enemy, "race", None)
                    race_value = getattr(enemy_race, "value", enemy_race)
                    if str(race_value or "").strip().lower() == "draconian":
                        count += 1
        return count

    def _survival_score(self, unit) -> int:
        score = 0
        if getattr(unit, "status", None) == UnitState.ACTIVE:
            score += 80
        elif getattr(unit, "status", None) == UnitState.DEPLETED:
            score += 25
        return score

    def _frontline_score(self, unit, side: str) -> int:
        if not getattr(unit, "position", None) or unit.position[0] is None:
            return 0
        hex_obj = Hex.offset_to_axial(unit.position[0], unit.position[1])
        enemy_adj = self._adjacent_enemy_count(hex_obj, side)
        friendly_adj = self._adjacent_friendly_count(hex_obj, side)
        return enemy_adj * 30 + friendly_adj * 5

    # ---------- Movement ----------
    def execute_best_movement(self, side: str, attempt_invasion=None) -> bool:
        stacks = self._build_movable_stacks(side)
        if not stacks:
            return False

        objective_hexes = self._objective_hexes_for_side(side)
        candidates = []
        eval_count = 0

        for stack in stacks:
            range_result = self.movement_service.get_reachable_hexes(stack)
            if not range_result.reachable_coords and not range_result.neutral_warning_coords:
                continue
            
            scored = []
            # 1. Evaluate regular moves
            for coords in range_result.reachable_coords:
                if eval_count >= self.AI_MAX_MOVE_EVAL:
                    break
                eval_count += 1
                score = self._score_move_target(stack, coords, objective_hexes, side)
                scored.append((score, stack, coords, None, False))
            
            # 2. Evaluate invasion moves (neutral entry)
            # Only consider if this is Highlord (HL) as per rules, though side check handles it.
            if side == HL:
                for coords in range_result.neutral_warning_coords:
                    if eval_count >= self.AI_MAX_MOVE_EVAL:
                        break
                    eval_count += 1
                    
                    # Identify target country
                    target_hex = Hex.offset_to_axial(coords[0], coords[1])
                    country = self.game_state.get_country_by_hex(coords[0], coords[1])
                    if not country or getattr(country, "allegiance", None) != NEUTRAL:
                        continue
                    
                    # Score invasion
                    inv_score = self._score_invasion_target(country.id, side)
                    
                    # Adjust score for specific move distance/logistics if needed
                    # For now, use the strategic invasion score directly, 
                    # possibly ensuring it's > threshold to be worth triggering war.
                    if inv_score > self.AI_MOVE_EXEC_THRESHOLD:
                        scored.append((inv_score, stack, coords, country.id, True))

            scored.sort(key=lambda item: item[0], reverse=True)
            candidates.extend(scored[: self.AI_MOVE_TOPK_PER_STACK])
            if eval_count >= self.AI_MAX_MOVE_EVAL:
                break

        if not candidates:
            return False

        candidates.sort(key=lambda item: item[0], reverse=True)
        for score, stack, coords, country_id, is_invasion in candidates:
            if score < self.AI_MOVE_EXEC_THRESHOLD:
                return False
            if is_invasion:
                if callable(attempt_invasion) and country_id:
                    attempt_invasion(country_id)
                    print(f"AI invasion score {score}: attempted invasion of {country_id}.")
                    return True
                continue
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
            defenders_before = [
                u for u in self.game_state.get_units_at(target_hex)
                if getattr(u, "is_on_map", False)
                and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
            ]
            resolution = self.game_state.resolve_combat(attackers, target_hex)
            show_combat_result_popup(
                self.game_state,
                title="Combat Details",
                attackers=attackers,
                defenders=defenders_before,
                resolution=resolution,
                context="ai_combat",
                target_hex=target_hex,
            )
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

        relief_bonus = self._stack_relief_bonus(stack, target_coords, side)
        return int(dist_gain * 20 + enemy_here * 60 + enemy_adj * 25 + friendly_adj * 8 + risk + relief_bonus)

    def _score_deployment_hex(self, unit, coords: tuple[int, int], objective_hexes: set[tuple[int, int]]) -> int:
        target_hex = Hex.offset_to_axial(coords[0], coords[1])
        side = getattr(unit, "allegiance", None)
        dist = self._min_distance_to_objectives(coords, objective_hexes)
        friendly_adj = self._adjacent_friendly_count(target_hex, side)
        enemy_adj = self._adjacent_enemy_count(target_hex, side)
        return int((0 if dist >= 999 else -dist * 12) + friendly_adj * 10 - enemy_adj * 14)

    def _is_trapped_mountain_deploy(self, unit, coords: tuple[int, int]) -> bool:
        target_hex = Hex.offset_to_axial(coords[0], coords[1])
        terrain = self.game_state.map.get_terrain(target_hex)
        if terrain != TerrainType.MOUNTAIN:
            return False
        for neighbor in target_hex.neighbors():
            col, row = neighbor.axial_to_offset()
            if not self.game_state.is_hex_in_bounds(col, row):
                continue
            cost = self.game_state.map.get_movement_cost(unit, target_hex, neighbor)
            if cost != float("inf"):
                return False
        return True

    def _stack_relief_bonus(self, stack, target_coords: tuple[int, int], side: str) -> int:
        if side != HL:
            return 0
        if not stack:
            return 0
        if not any(getattr(u, "is_army", lambda: False)() for u in stack):
            return 0
        start_pos = getattr(stack[0], "position", None)
        if not start_pos or start_pos[0] is None:
            return 0
        if (start_pos[0], start_pos[1]) == target_coords:
            return 0

        start_hex = Hex.offset_to_axial(start_pos[0], start_pos[1])
        loc = self.game_state.map.get_location(start_hex)
        if not loc:
            return 0
        is_city = loc.loc_type == LocType.CITY.value
        is_capital = bool(loc.is_capital)
        if not (is_city or is_capital):
            return 0

        country = self.game_state.get_country_by_hex(start_pos[0], start_pos[1])
        if not country:
            return 0
        ready_exists = any(
            getattr(u, "allegiance", None) == side
            and getattr(u, "status", None) == UnitState.READY
            and not getattr(u, "is_on_map", False)
            and getattr(u, "land", None) == country.id
            for u in self.game_state.units
        )
        if not ready_exists:
            return 0

        units_here = [
            u
            for u in self.game_state.get_units_at(start_hex)
            if getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) == side
        ]
        army_count = sum(1 for u in units_here if getattr(u, "is_army", lambda: False)())
        if army_count < 3:
            return 0

        return 260

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

    def _score_invasion_target(self, country_id: str, side: str) -> int:
        """Score invasion target country for Highlord AI"""
        country = self.game_state.countries.get(country_id)
        if not country or getattr(country, "allegiance", None) != NEUTRAL:
            return -9999

        success_prob = self._estimate_invasion_success_likelihood(country_id, side)
        activation_score = success_prob * 150
        strength_score = 50 if success_prob > 0.8 else 0
        strategic_score = self._country_objective_relevance(side, country_id) * 60
        engagement_penalty = self._current_engagement_penalty(side)
        border_bonus = self._border_presence_bonus(country_id, side) * 10

        return int(activation_score + strength_score + strategic_score - engagement_penalty + border_bonus)

    def _estimate_invasion_success_likelihood(self, country_id: str, side: str) -> float:
        """Estimate likelihood of successful invasion based on military balance."""
        country = self.game_state.countries.get(country_id)
        if not country:
            return 0.0
        
        invasion_data = self.movement_service.get_invasion_force(country_id)
        invader_sp = invasion_data.get("strength", 0)
        defender_sp = getattr(country, "strength", 0)
        
        modifier = 0
        if hasattr(self.diplomacy_service, "_invasion_modifier"):
            modifier = self.diplomacy_service._invasion_modifier(invader_sp, defender_sp)
            
        base_hl = (country.alignment[1] if country.alignment else 0) + modifier
        return min(1.0, max(0.0, base_hl / 10.0))

    def _current_engagement_penalty(self, side: str) -> int:
        """Penalize if Highlord is already engaged in multiple conflicts"""
        combat_zones = len([u for u in self.game_state.units
                           if getattr(u, "allegiance", None) == side
                           and getattr(u, "attacked_this_turn", False)])
        if combat_zones >= 3:
            return 120
        elif combat_zones >= 2:
            return 60
        return 0

    def _border_presence_bonus(self, country_id: str, side: str) -> int:
        """Bonus for having units positioned at country borders"""
        invasion_data = self.movement_service.get_invasion_force(country_id)
        return min(3, len(invasion_data.get("border_hexes", set())))
