from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.content import loader
from src.content.config import AI_STANCE_DATA
from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import UnitType, UnitState, LocType, TerrainType, UnitRace
from src.game.map import Hex
from src.game.combat_reporting import show_combat_result_popup


class BaselineAIPlayer:
    AI_MAX_MOVE_EVAL = 80
    AI_MAX_COMBAT_EVAL = 40
    AI_MOVE_TOPK_PER_STACK = 8
    AI_MOVE_EXEC_THRESHOLD = 20
    AI_LATE_GAME_MOVE_THRESHOLD = 30
    AI_COMBAT_EXEC_THRESHOLD = 25
    AI_LATE_GAME_COMBAT_EXEC_THRESHOLD = 35
    AI_BACKTRACK_PENALTY = 220
    AI_REVISIT_PENALTY = 70
    AI_CAPITAL_GARRISON_VACATE_PENALTY = 280
    AI_AIR_TETHER_MAX_OFFENSIVE = 3
    AI_AIR_TETHER_MAX_DEFENSIVE = 2

    def __init__(self, game_state, movement_service, diplomacy_service):
        self.game_state = game_state
        self.movement_service = movement_service
        self.diplomacy_service = diplomacy_service
        self._movement_phase_key = None
        self._unit_last_position = {}
        self._unit_visit_counts = defaultdict(lambda: defaultdict(int))
        self._side_strategy_cache = {}
        self._combat_phase_key = None
        self._failed_combat_targets = defaultdict(set)
        self._ai_stance_matrix = loader.load_ai_stance_csv(AI_STANCE_DATA)

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
        if side == HL:
            deployed += self._deploy_hl_dragon_pairs(
                objective_hexes=objective_hexes,
                allow_territory_wide=allow_territory_wide,
                country_filter=country_filter,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
        if self._transport_campaign_mode_active(side):
            deployed += self._deploy_transport_campaign_pairs(
                side=side,
                objective_hexes=objective_hexes,
                allow_territory_wide=allow_territory_wide,
                country_filter=country_filter,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )

        for unit in ready_units:
            if getattr(unit, "is_on_map", False):
                continue
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

    def _deploy_transport_campaign_pairs(
        self,
        side: str,
        objective_hexes: set[tuple[int, int]],
        allow_territory_wide: bool,
        country_filter: str | None,
        invasion_deployment_active: bool,
        invasion_deployment_allegiance: str | None,
        invasion_deployment_country_id: str | None,
    ) -> int:
        deployed = 0
        while True:
            ready = [
                u for u in self.game_state.units
                if getattr(u, "allegiance", None) == side
                and getattr(u, "status", None) == UnitState.READY
                and not getattr(u, "is_on_map", False)
            ]
            if country_filter:
                ready = [u for u in ready if getattr(u, "land", None) == country_filter]
            fleets = [u for u in ready if u.is_fleet()]
            armies = [
                u for u in ready
                if hasattr(u, "is_army")
                and u.is_army()
                and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            ]
            if not fleets or not armies:
                break

            best = None
            best_score = float("-inf")
            for fleet in fleets:
                fleet_valid = self.game_state.get_valid_deployment_hexes(fleet, allow_territory_wide=allow_territory_wide) or []
                if not fleet_valid:
                    continue
                fleet_valid_set = set((int(c[0]), int(c[1])) for c in fleet_valid)
                for army in armies:
                    army_valid = self.game_state.get_valid_deployment_hexes(army, allow_territory_wide=allow_territory_wide) or []
                    army_valid = [c for c in army_valid if not self._is_trapped_mountain_deploy(army, c)]
                    if not army_valid:
                        continue
                    joint = [c for c in army_valid if (int(c[0]), int(c[1])) in fleet_valid_set]
                    for c in joint:
                        coords = (int(c[0]), int(c[1]))
                        score = self._score_deployment_hex(fleet, coords, objective_hexes)
                        score += self._score_deployment_hex(army, coords, objective_hexes)
                        score += 240
                        if score > best_score:
                            best_score = score
                            best = (fleet, army, coords)
            if best is None:
                break

            fleet, army, coords = best
            target_hex = Hex.offset_to_axial(coords[0], coords[1])
            fleet_result = self.game_state.deployment_service.deploy_unit(
                fleet,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if not fleet_result.success:
                break
            army_result = self.game_state.deployment_service.deploy_unit(
                army,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if not army_result.success:
                # Keep fleet deployment if rollback is not guaranteed-safe in all states.
                deployed += 1
                continue
            deployed += 2
        return deployed

    def _deploy_hl_dragon_pairs(
        self,
        objective_hexes: set[tuple[int, int]],
        allow_territory_wide: bool,
        country_filter: str | None,
        invasion_deployment_active: bool,
        invasion_deployment_allegiance: str | None,
        invasion_deployment_country_id: str | None,
    ) -> int:
        """Deploy HL dragon wings with commander in same hex: same-flight Highlord, fallback Emperor."""
        deployed = 0
        ready = [
            u for u in self.game_state.units
            if getattr(u, "allegiance", None) == HL
            and getattr(u, "status", None) == UnitState.READY
            and not getattr(u, "is_on_map", False)
        ]
        if country_filter:
            ready = [u for u in ready if getattr(u, "land", None) == country_filter]

        wings = [
            u for u in ready
            if u.is_wing()
            and bool(getattr(getattr(u, "spec", None), "dragonflight", None))
        ]
        if not wings:
            return 0

        leaders = [
            u for u in ready
            if getattr(u, "unit_type", None) in (UnitType.HIGHLORD, UnitType.EMPEROR)
        ]

        used_leader_ids = set()
        wings.sort(key=lambda u: (str(getattr(u, "id", "")), int(getattr(u, "ordinal", 1))))
        for wing in wings:
            if getattr(wing, "is_on_map", False):
                continue
            flight = str(getattr(getattr(wing, "spec", None), "dragonflight", "") or "").strip().lower()
            if not flight:
                continue

            commander = self._pick_hl_dragon_commander_for_deploy(wing, leaders, used_leader_ids)
            if not commander:
                # Keep wing undeployed if no valid commander is ready.
                continue

            wing_valid = self.game_state.get_valid_deployment_hexes(
                wing, allow_territory_wide=allow_territory_wide
            )
            commander_valid = self.game_state.get_valid_deployment_hexes(
                commander, allow_territory_wide=allow_territory_wide
            )
            wing_valid = [c for c in wing_valid if not self._is_trapped_mountain_deploy(wing, c)]
            commander_valid_set = set(commander_valid or [])
            joint = [c for c in wing_valid if c in commander_valid_set]
            if not joint:
                continue

            best = max(joint, key=lambda c: self._score_deployment_hex(wing, c, objective_hexes))
            target_hex = Hex.offset_to_axial(best[0], best[1])
            wing_result = self.game_state.deployment_service.deploy_unit(
                wing,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if not wing_result.success:
                continue

            leader_result = self.game_state.deployment_service.deploy_unit(
                commander,
                target_hex,
                invasion_deployment_active=invasion_deployment_active,
                invasion_deployment_allegiance=invasion_deployment_allegiance,
                invasion_deployment_country_id=invasion_deployment_country_id,
            )
            if not leader_result.success:
                # Roll back wing deployment to keep pair invariant.
                try:
                    wing.position = (None, None)
                    wing.status = UnitState.READY
                    wing.is_transported = False
                    wing.transport_host = None
                    self.game_state.map.remove_unit_from_spatial_map(wing)
                except Exception:
                    pass
                continue

            used_leader_ids.add(id(commander))
            deployed += 2

        return deployed

    def _pick_hl_dragon_commander_for_deploy(self, wing, leaders, used_leader_ids):
        flight = str(getattr(getattr(wing, "spec", None), "dragonflight", "") or "").strip().lower()
        same_flight = [
            l for l in leaders
            if id(l) not in used_leader_ids
            and not getattr(l, "is_on_map", False)
            and getattr(l, "unit_type", None) == UnitType.HIGHLORD
            and str(getattr(getattr(l, "spec", None), "dragonflight", "") or "").strip().lower() == flight
        ]
        if same_flight:
            return sorted(same_flight, key=lambda u: (str(getattr(u, "id", "")), int(getattr(u, "ordinal", 1))))[0]

        emperors = [
            l for l in leaders
            if id(l) not in used_leader_ids
            and not getattr(l, "is_on_map", False)
            and getattr(l, "unit_type", None) == UnitType.EMPEROR
        ]
        if emperors:
            return sorted(emperors, key=lambda u: (str(getattr(u, "id", "")), int(getattr(u, "ordinal", 1))))[0]
        return None

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
        profile = self._side_strategy_profile(side)
        for country in neutrals[:10]:
            attempt = self.diplomacy_service.build_activation_attempt(country.id)
            if not attempt:
                continue
            unit_count = sum(1 for u in self.game_state.units if getattr(u, "land", None) == country.id)
            alignment = self._country_alignment_for_side(country, side)
            align_bonus = alignment * 80 + (220 if alignment >= 5 else 0)
            proximity = self._country_proximity_to_side(country.id, side)
            if profile.get("is_offensive", False):
                distance_score = int(proximity * 18)
            else:
                distance_score = int(-proximity * 20)
            score = (
                int(getattr(attempt, "target_rating", 0) or 0) * 20
                + unit_count * 12
                + align_bonus
                + distance_score
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

    @staticmethod
    def _country_alignment_for_side(country, side: str) -> int:
        alignment = getattr(country, "alignment", None) or (0, 0)
        if side == HL:
            return int(alignment[1] if len(alignment) > 1 else 0)
        if side == WS:
            return int(alignment[0] if len(alignment) > 0 else 0)
        return 0

    def _country_proximity_to_side(self, country_id: str, side: str) -> float:
        country = self.game_state.countries.get(country_id)
        if not country:
            return 0.0
        target_hexes = [
            Hex.offset_to_axial(loc.coords[0], loc.coords[1])
            for loc in country.locations.values()
            if getattr(loc, "coords", None)
        ]
        if not target_hexes:
            return 0.0

        side_units = [
            u for u in self.game_state.units
            if getattr(u, "is_on_map", False)
            and getattr(u, "allegiance", None) == side
            and getattr(u, "position", None)
            and u.position[0] is not None
            and hasattr(u, "is_army")
            and u.is_army()
            and getattr(u, "transport_host", None) is None
        ]
        if not side_units:
            return 0.0

        distances = []
        for unit in side_units:
            start = Hex.offset_to_axial(unit.position[0], unit.position[1])
            distances.append(min(start.distance_to(dst) for dst in target_hexes))
        if not distances:
            return 0.0
        avg_distance = sum(distances) / len(distances)
        return float(max(0.0, min(12.0, avg_distance)))

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
        if unit.is_leader():
            score += 160
        elif unit.is_army():
            score += 120
        elif unit.is_wing():
            score += 90
        elif unit.is_fleet():
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
        self._ensure_movement_phase_state(side)
        if self._execute_transport_actions(side):
            return True
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
                if not self._is_move_candidate_allowed(stack, coords, side, objective_hexes):
                    continue
                eval_count += 1
                score = self._score_move_target(stack, coords, objective_hexes, side)
                scored.append((score, stack, coords, None, False))
            
            # 2. Evaluate invasion moves (neutral entry)
            # Only consider if this is Highlord (HL) as per rules, though side check handles it.
            if side == HL:
                for coords in range_result.neutral_warning_coords:
                    if eval_count >= self.AI_MAX_MOVE_EVAL:
                        break
                    if not self._is_move_candidate_allowed(stack, coords, side, objective_hexes):
                        continue
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

        exec_threshold = self._current_move_exec_threshold()
        candidates.sort(key=lambda item: item[0], reverse=True)
        has_non_backtrack_exec = any(
            (
                score >= exec_threshold
                and not is_invasion
                and not self._is_immediate_backtrack(stack, coords)
            )
            for score, stack, coords, country_id, is_invasion in candidates
        )
        for score, stack, coords, country_id, is_invasion in candidates:
            if score < exec_threshold:
                return False
            if is_invasion:
                if callable(attempt_invasion) and country_id:
                    attempt_invasion(country_id)
                    print(f"AI invasion score {score}: attempted invasion of {country_id}.")
                    return True
                continue
            if has_non_backtrack_exec and self._is_immediate_backtrack(stack, coords):
                continue
            before_positions = {
                id(unit): tuple(unit.position)
                for unit in stack
                if getattr(unit, "position", None) and unit.position[0] is not None
            }
            target_hex = Hex.offset_to_axial(coords[0], coords[1])
            result = self.movement_service.move_units_to_hex(stack, target_hex)
            if not result.errors and result.moved:
                self._record_stack_move(result.moved, before_positions, coords)
                print(f"AI move score {score}: {len(result.moved)} unit(s) to {coords}")
                return True
        return False

    def _is_move_candidate_allowed(
        self,
        stack,
        target_coords: tuple[int, int],
        side: str,
        objective_hexes: set[tuple[int, int]],
    ) -> bool:
        if not stack:
            return False
        start = getattr(stack[0], "position", None)
        if not start or start[0] is None:
            return False
        start_xy = (int(start[0]), int(start[1]))
        target_xy = (int(target_coords[0]), int(target_coords[1]))

        if start_xy != target_xy and self._would_leave_capital_undefended_after_departure(start_xy, stack, side):
            return False

        if self._is_empty_fleet_stack(stack):
            if not self._fleet_escape_only_objective_active(side):
                if not self._empty_fleet_move_is_transport_relevant(stack, start_xy, target_xy, side, objective_hexes):
                    return False
        elif self._is_loaded_fleet_stack(stack):
            if self._transport_campaign_mode_active(side) and not self._fleet_escape_only_objective_active(side):
                if not self._loaded_fleet_move_is_objective_relevant(stack, start_xy, target_xy, objective_hexes):
                    return False

        if self._violates_air_support_tether(stack, start_xy, target_xy, side, objective_hexes):
            return False

        return True

    def _current_move_exec_threshold(self) -> int:
        if self._is_late_game():
            return self.AI_LATE_GAME_MOVE_THRESHOLD
        return self.AI_MOVE_EXEC_THRESHOLD

    def _ensure_movement_phase_state(self, side: str):
        phase = getattr(self.game_state, "phase", None)
        turn = getattr(self.game_state, "turn", None)
        key = (turn, side, phase)
        if self._movement_phase_key == key:
            return
        self._movement_phase_key = key
        self._side_strategy_cache = {}
        self._unit_last_position = {}
        self._unit_visit_counts = defaultdict(lambda: defaultdict(int))
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != side:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None:
                continue
            marker = id(unit)
            start = (int(pos[0]), int(pos[1]))
            self._unit_last_position[marker] = start
            self._unit_visit_counts[marker][start] += 1

    def _record_stack_move(self, moved_units, before_positions: dict[int, tuple[int, int]], to_coords: tuple[int, int]):
        to_xy = (int(to_coords[0]), int(to_coords[1]))
        for unit in moved_units:
            marker = id(unit)
            previous = before_positions.get(marker)
            if previous:
                self._unit_last_position[marker] = previous
            self._unit_visit_counts[marker][to_xy] += 1

    def _is_immediate_backtrack(self, stack, target_coords: tuple[int, int]) -> bool:
        if not stack:
            return False
        target_xy = (int(target_coords[0]), int(target_coords[1]))
        backtrack_votes = 0
        movable = 0
        for unit in stack:
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None:
                continue
            movable += 1
            marker = id(unit)
            last = self._unit_last_position.get(marker)
            if last and target_xy == last:
                backtrack_votes += 1
        return movable > 0 and backtrack_votes == movable

    def _execute_transport_actions(self, side: str) -> bool:
        # 1) Unboard armies from fleets/citadels that have reached land.
        if self._attempt_unboard_passengers(side):
            return True

        # 2) Ensure dragon wings have valid commanders.
        if self._attempt_board_dragon_commanders(side):
            return True

        # 3) Board armies/leaders onto fleets/citadels for transport.
        if self._attempt_board_armies(side):
            return True

        return False

    def _attempt_unboard_passengers(self, side: str) -> bool:
        objective_hexes = self._objective_hexes_for_side(side)
        profile = self._side_strategy_profile(side)
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != side:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "unit_type", None) not in (UnitType.FLEET, UnitType.CITADEL):
                continue
            passengers = list(getattr(unit, "passengers", []) or [])
            if not passengers:
                continue
            if not getattr(unit, "position", None):
                continue
            carrier_hex = Hex.offset_to_axial(*unit.position)
            terrain = self.game_state.map.get_terrain(carrier_hex)
            if terrain in (TerrainType.OCEAN, TerrainType.MAELSTROM):
                continue
            if not getattr(unit, "moved_this_turn", False) and getattr(unit, "movement_points", 0) > 0:
                continue
            if not self._should_attempt_unboard_at_hex(carrier_hex, side, objective_hexes, profile):
                continue
            need = self._required_ground_unboard_garrison(carrier_hex, side, objective_hexes, profile)
            on_hex_ground = self._friendly_ground_count_at_hex(carrier_hex, side)
            unboarded = False
            unboarded_count = 0
            for p in passengers:
                if hasattr(p, "is_leader") and p.is_leader():
                    continue
                if not (hasattr(p, "is_army") and p.is_army()):
                    continue
                if on_hex_ground + unboarded_count >= need:
                    break
                if self.game_state.unboard_unit(p):
                    unboarded = True
                    unboarded_count += 1
            if unboarded:
                print(f"AI unboarded passengers from {unit.id} at {carrier_hex.axial_to_offset()}.")
                return True
        return False

    def _attempt_board_dragon_commanders(self, side: str) -> bool:
        for wing in self.game_state.units:
            if getattr(wing, "allegiance", None) != side:
                continue
            if not getattr(wing, "is_on_map", False):
                continue
            if getattr(wing, "unit_type", None) != UnitType.WING:
                continue
            if not getattr(wing, "position", None):
                continue
            if self.movement_service._dragon_interceptor_has_required_commander(wing):
                continue
            leaders = [
                leader for leader in self._leaders_in_hex(wing)
                if self._leader_can_command_wing(leader, wing, side)
            ]
            leaders.sort(key=lambda l: self._dragon_commander_priority(l, wing, side), reverse=True)
            for leader in leaders:
                if not self._leader_can_command_wing(leader, wing, side):
                    continue
                if self.game_state.board_unit(wing, leader):
                    print(f"AI boarded {leader.id} onto {wing.id} for command.")
                    return True
        return False

    def _dragon_commander_priority(self, leader, wing, side: str) -> int:
        if side == HL:
            if getattr(leader, "unit_type", None) == UnitType.HIGHLORD:
                wing_flight = str(getattr(getattr(wing, "spec", None), "dragonflight", "") or "").strip().lower()
                leader_flight = str(getattr(getattr(leader, "spec", None), "dragonflight", "") or "").strip().lower()
                if wing_flight and leader_flight and wing_flight == leader_flight:
                    return 200
                return 50
            if getattr(leader, "unit_type", None) == UnitType.EMPEROR:
                return 150
            return 0
        if getattr(leader, "race", None) in (UnitRace.ELF, UnitRace.SOLAMNIC):
            return 100
        return 0

    def _attempt_board_armies(self, side: str) -> bool:
        profile = self._side_strategy_profile(side)
        objective_hexes = self._objective_hexes_for_side(side)
        best_action = None
        best_score = float("-inf")

        for carrier in self.game_state.units:
            if getattr(carrier, "allegiance", None) != side:
                continue
            if not getattr(carrier, "is_on_map", False):
                continue
            if getattr(carrier, "unit_type", None) not in (UnitType.FLEET, UnitType.CITADEL):
                continue
            if not getattr(carrier, "position", None):
                continue
            if getattr(carrier, "moved_this_turn", False):
                continue

            for unit in self._units_in_hex(carrier):
                if unit is carrier:
                    continue
                if getattr(unit, "transport_host", None) is not None:
                    continue
                if not ((hasattr(unit, "is_army") and unit.is_army()) or (hasattr(unit, "is_leader") and unit.is_leader())):
                    continue
                pos = getattr(unit, "position", None)
                origin = (int(pos[0]), int(pos[1])) if pos and pos[0] is not None else None
                if origin and self._would_leave_capital_undefended_after_departure(origin, [unit], side):
                    continue
                score = self._score_boarding_action(unit, carrier, side, objective_hexes, profile)
                if score > best_score:
                    best_score = score
                    best_action = (carrier, unit, score)

        if best_action is None or best_score < 30:
            return False

        carrier, unit, score = best_action
        if self.game_state.board_unit(carrier, unit):
            print(f"AI boarded {unit.id} onto {carrier.id} (score {int(score)}).")
            return True
        return False

    def _score_boarding_action(self, unit, carrier, side: str, objective_hexes: set[tuple[int, int]], profile: dict[str, Any]) -> float:
        if not getattr(unit, "position", None) or unit.position[0] is None:
            return -9999
        start = (int(unit.position[0]), int(unit.position[1]))
        start_dist = self._min_distance_to_objectives(start, objective_hexes)
        island_redeploy = self._is_islanded_hex(start) and self._friendly_ground_count_at_coords(start, side) > 1
        if start_dist >= 999 and not island_redeploy:
            return -9999

        candidate_hexes = self._carrier_transport_destinations(carrier, unit)
        if not candidate_hexes:
            return -9999
        end_dist = min(self._min_distance_to_objectives(c, objective_hexes) for c in candidate_hexes)
        dist_gain = start_dist - end_dist
        if dist_gain <= 0 and not island_redeploy:
            return -9999

        score = max(0, dist_gain) * 55
        if island_redeploy:
            score += 220
        if profile.get("is_offensive", False):
            score += 40
        if profile.get("is_defensive", False):
            score -= 25

        # Defensive posture can still board if it creates substantial strategic progress.
        if profile.get("is_defensive", False) and dist_gain < 3:
            score -= 120

        if hasattr(unit, "is_leader") and unit.is_leader():
            score -= 40
            # Leaders should generally board only with armies as escort.
            passengers = list(getattr(carrier, "passengers", []) or [])
            if not any(hasattr(p, "is_army") and p.is_army() for p in passengers):
                score -= 80
        return float(score)

    def _carrier_transport_destinations(self, carrier, passenger) -> list[tuple[int, int]]:
        out = []
        if not getattr(carrier, "position", None):
            return out
        try:
            range_result = self.movement_service.get_reachable_hexes([carrier])
            coords = list(getattr(range_result, "reachable_coords", []) or [])
        except Exception:
            coords = []
        coords.append((int(carrier.position[0]), int(carrier.position[1])))

        seen = set()
        for col, row in coords:
            key = (int(col), int(row))
            if key in seen:
                continue
            seen.add(key)
            hex_obj = Hex.offset_to_axial(key[0], key[1])
            if not self.game_state.map.can_unit_land_on_hex(passenger, hex_obj):
                continue
            if not self.game_state.map.can_stack_move_to([passenger], hex_obj):
                continue
            out.append(key)
        return out

    def _would_leave_capital_without_defender_after_board(self, unit, side: str) -> bool:
        pos = getattr(unit, "position", None)
        if not pos or pos[0] is None:
            return False
        origin = (int(pos[0]), int(pos[1]))
        return self._would_leave_capital_undefended_after_departure(origin, [unit], side)

    @staticmethod
    def _is_capital_defender_unit(unit) -> bool:
        if not getattr(unit, "is_on_map", False):
            return False
        if getattr(unit, "transport_host", None) is not None:
            return False
        if getattr(unit, "unit_type", None) == UnitType.WING:
            return True
        return bool(hasattr(unit, "is_army") and unit.is_army() and getattr(unit, "unit_type", None) != UnitType.FLEET)

    def _capital_country_at_coords(self, coords: tuple[int, int], side: str):
        for country in self.game_state.countries.values():
            if getattr(country, "allegiance", None) != side:
                continue
            capital = getattr(country, "capital", None)
            if not capital or not getattr(capital, "coords", None):
                continue
            if tuple(capital.coords) == tuple(coords):
                return country
        return None

    def _would_leave_capital_undefended_after_departure(
        self,
        origin_coords: tuple[int, int],
        departing_units,
        side: str,
    ) -> bool:
        if not origin_coords:
            return False
        if self._capital_country_at_coords(origin_coords, side) is None:
            return False
        origin_hex = Hex.offset_to_axial(origin_coords[0], origin_coords[1])
        defenders_here = [
            u
            for u in self.game_state.get_units_at(origin_hex)
            if self._is_capital_defender_unit(u) and getattr(u, "allegiance", None) == side
        ]
        if not defenders_here:
            return False
        leaving_ids = {
            id(u)
            for u in (departing_units or [])
            if self._is_capital_defender_unit(u)
            and getattr(u, "allegiance", None) == side
            and getattr(u, "position", None)
            and (int(u.position[0]), int(u.position[1])) == tuple(origin_coords)
        }
        remaining = len([u for u in defenders_here if id(u) not in leaving_ids])
        return remaining < 1

    def _leaders_in_hex(self, unit):
        if not getattr(unit, "position", None):
            return []
        hex_obj = Hex.offset_to_axial(*unit.position)
        return [
            u for u in self.game_state.get_units_at(hex_obj)
            if getattr(u, "is_on_map", False)
            and getattr(u, "transport_host", None) is None
            and hasattr(u, "is_leader") and u.is_leader()
        ]

    def _units_in_hex(self, unit):
        if not getattr(unit, "position", None):
            return []
        hex_obj = Hex.offset_to_axial(*unit.position)
        return [
            u for u in self.game_state.get_units_at(hex_obj)
            if getattr(u, "is_on_map", False)
        ]

    def _leader_can_command_wing(self, leader, wing, side: str) -> bool:
        if not hasattr(leader, "is_leader") or not leader.is_leader():
            return False
        if side == HL:
            if leader.unit_type == UnitType.EMPEROR:
                return True
            if leader.unit_type == UnitType.HIGHLORD:
                wing_flight = getattr(getattr(wing, "spec", None), "dragonflight", None)
                leader_flight = getattr(getattr(leader, "spec", None), "dragonflight", None)
                return bool(wing_flight and leader_flight and wing_flight == leader_flight)
            return False
        leader_race = getattr(leader, "race", None)
        return leader_race in (UnitRace.ELF, UnitRace.SOLAMNIC)

    # ---------- Combat ----------
    def execute_best_combat(self, side: str) -> bool:
        self._ensure_combat_phase_state(side)
        candidates = self._combat_candidates(side)
        if not candidates:
            return False

        exec_threshold = self._current_combat_exec_threshold()
        candidates.sort(key=lambda item: item["score"], reverse=True)
        for candidate in candidates:
            if candidate["score"] < exec_threshold:
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
            self._record_combat_outcome(side, target_hex, defenders_before, resolution)
            print(
                f"AI combat score {candidate['score']}: "
                f"{len(attackers)} attacker(s) vs {target_hex.axial_to_offset()}"
            )
            return True
        return False

    def _current_combat_exec_threshold(self) -> int:
        return self.AI_LATE_GAME_COMBAT_EXEC_THRESHOLD if self._is_late_game() else self.AI_COMBAT_EXEC_THRESHOLD

    def _ensure_combat_phase_state(self, side: str):
        phase = getattr(self.game_state, "phase", None)
        turn = getattr(self.game_state, "turn", None)
        key = (turn, side, phase)
        if self._combat_phase_key == key:
            return
        self._combat_phase_key = key
        self._failed_combat_targets = defaultdict(set)

    def _record_combat_outcome(self, side: str, target_hex: Hex, defenders_before, resolution):
        if not target_hex:
            return
        target = target_hex.axial_to_offset()
        result = (resolution or {}).get("result", "-/-")
        parts = result.split("/")
        attacker_result = parts[0] if len(parts) > 0 else "-"
        defender_result = parts[1] if len(parts) > 1 else "-"

        defenders_after = [
            u for u in self.game_state.get_units_at(target_hex)
            if getattr(u, "is_on_map", False)
            and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
        ]
        no_defender_reduction = len(defenders_after) >= len(defenders_before or [])
        suicidal_fail = attacker_result == "E" and defender_result == "-"
        if suicidal_fail or no_defender_reduction:
            self._failed_combat_targets[side].add(target)

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
            combat_ground = [
                u for u in units
                if hasattr(u, "is_army")
                and u.is_army()
                and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            ]
            leaders = [u for u in units if hasattr(u, "is_leader") and u.is_leader()]
            ground = combat_ground + leaders
            air = [u for u in units if (u.is_wing() or u.is_citadel())]
            fleet = [u for u in units if u.is_fleet()]
            # Never move leaders alone; leaders move only as part of escorted ground stacks.
            if combat_ground:
                stacks.append(sorted(ground, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
            if air:
                stacks.append(sorted(air, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
            if fleet:
                loaded_fleet = [f for f in fleet if self._fleet_has_ground_or_leader_passengers(f)]
                empty_fleet = [f for f in fleet if not self._fleet_has_ground_or_leader_passengers(f)]
                if loaded_fleet:
                    stacks.append(sorted(loaded_fleet, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
                if empty_fleet:
                    stacks.append(sorted(empty_fleet, key=lambda u: (u.id, int(getattr(u, "ordinal", 1)))))
        return stacks

    def _score_move_target(self, stack, target_coords, objective_hexes: set[tuple[int, int]], side: str) -> int:
        target_hex = Hex.offset_to_axial(target_coords[0], target_coords[1])
        start = stack[0].position if stack and getattr(stack[0], "position", None) else target_coords
        urgency = self._objective_urgency_multiplier()
        is_late = self._is_late_game()
        profile = self._side_strategy_profile(side)
        major_objective_hexes = self._major_objective_hexes_for_side(side)

        # Progress momentum: reward sustained objective approach over this and prior move.
        start_dist = self._min_distance_to_objectives(start, objective_hexes)
        end_dist = self._min_distance_to_objectives(target_coords, objective_hexes)
        dist_gain = (start_dist - end_dist) if start_dist < 999 else 0
        prev_dist_gain = 0
        lead_marker = id(stack[0]) if stack else None
        if lead_marker and start and start[0] is not None:
            prev = self._unit_last_position.get(lead_marker)
            if prev:
                prev_dist = self._min_distance_to_objectives(prev, objective_hexes)
                prev_dist_gain = (prev_dist - start_dist) if prev_dist < 999 else 0

        enemy_adj = self._adjacent_enemy_count(target_hex, side)
        friendly_adj = self._adjacent_friendly_count(target_hex, side)
        enemy_here = len(
            [
                u
                for u in self.game_state.get_units_at(target_hex)
                if getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
            ]
        )
        own_here = len(
            [
                u
                for u in self.game_state.get_units_at(target_hex)
                if getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) == side
            ]
        )
        has_ground = any(getattr(u, "is_army", lambda: False)() for u in stack)
        has_air_only = (not has_ground) and any(
            getattr(u, "unit_type", None) in (UnitType.WING, UnitType.CITADEL)
            for u in stack
        )

        risk = 0
        if enemy_adj > 0 and friendly_adj == 0:
            risk -= 140
        if enemy_adj >= 3:
            risk -= 80

        role_w = self._stack_role_weights(stack, side)
        progress_score = int(prev_dist_gain * 12 + dist_gain * 20 * role_w["objective"] * urgency)
        contact_score = int(enemy_here * 60 + enemy_adj * 25 * role_w["threat"] + friendly_adj * 8 * role_w["cohesion"])

        backtrack_penalty = 0
        if self._is_immediate_backtrack(stack, target_coords):
            backtrack_penalty -= self.AI_BACKTRACK_PENALTY

        revisit_penalty = 0
        revisit_scale = 1.4 if self._is_late_game() else 1.0
        for unit in stack:
            marker = id(unit)
            visits = self._unit_visit_counts[marker].get((int(target_coords[0]), int(target_coords[1])), 0)
            if visits > 0:
                revisit_penalty -= int(self.AI_REVISIT_PENALTY * revisit_scale * visits)

        efficiency_bonus = 0
        est_cost = self._estimate_stack_move_cost(stack, target_coords)
        if est_cost > 0 and dist_gain > 0:
            efficiency_bonus += int((dist_gain * 24) / est_cost)
        elif est_cost > 0 and dist_gain <= 0:
            efficiency_bonus -= int(10 * role_w["objective"])

        frontier_bonus = 0
        if end_dist < start_dist and (enemy_adj > 0 or enemy_here > 0 or target_coords in objective_hexes):
            frontier_bonus += int((40 + 20 * min(enemy_adj + enemy_here, 4)) * urgency)

        objective_entry_bonus = 0
        if target_coords in objective_hexes and tuple(start) != tuple(target_coords):
            objective_entry_bonus += int(140 * urgency)
            if enemy_here > 0:
                # Conversion pressure: prioritize attacking into objective spaces.
                objective_entry_bonus += int(110 * urgency)

        low_value_penalty = 0
        if (
            dist_gain <= 0
            and enemy_adj == 0
            and enemy_here == 0
            and target_coords not in objective_hexes
            and friendly_adj <= 1
        ):
            low_value_penalty -= int(35 * urgency)

        late_distance_penalty = 0
        if is_late:
            if end_dist >= 999:
                late_distance_penalty -= int(260 * urgency)
            else:
                # End-game: moves that keep units far from objectives are expensive.
                late_distance_penalty -= int(max(0, end_dist - 2) * 14 * urgency)
            if dist_gain <= 0 and target_coords not in objective_hexes:
                late_distance_penalty -= int(30 * urgency)

        posture = profile.get("posture", "balanced")
        posture_adjust = 0
        if posture == "defensive":
            posture_adjust += int(friendly_adj * 12)
            posture_adjust -= int(enemy_here * 10)
            posture_adjust += int(self._hex_defense_value(target_coords) * 12)
        elif posture == "offensive":
            posture_adjust += int((enemy_adj * 10 + enemy_here * 18) * urgency)
            if has_ground and own_here > 0:
                posture_adjust += 35
            if has_ground and friendly_adj <= 1 and enemy_adj >= 2:
                posture_adjust -= 70
        elif posture == "escape":
            # Escape posture: avoid unnecessary fights unless they advance objective movement.
            posture_adjust -= int((enemy_adj * 10 + enemy_here * 20) * (1.2 if dist_gain <= 0 else 0.8))
        if self._is_fleet_only_stack(stack) and self._fleet_escape_only_objective_active(side):
            if target_coords in objective_hexes and dist_gain > 0:
                posture_adjust += 80
            posture_adjust += friendly_adj * 22
            posture_adjust -= enemy_adj * 28

        air_posture_adjust = 0
        if has_air_only and profile.get("victory_category") != "escape":
            if target_coords not in objective_hexes:
                air_posture_adjust -= 45
            if enemy_adj > 0:
                air_posture_adjust -= 40
            if enemy_here == 0 and target_coords in objective_hexes:
                air_posture_adjust += 90
        air_support_bonus = self._air_support_mobility_bonus(
            stack=stack,
            side=side,
            start_coords=(int(start[0]), int(start[1])) if start else target_coords,
            target_coords=target_coords,
            objective_hexes=objective_hexes,
            has_air_only=has_air_only,
        )
        transport_coordination_bonus = self._transport_coordination_bonus(
            stack=stack,
            side=side,
            start_coords=(int(start[0]), int(start[1])) if start else target_coords,
            target_coords=(int(target_coords[0]), int(target_coords[1])),
            objective_hexes=objective_hexes,
        )
        major_push_bonus = self._major_objective_push_bonus(
            stack=stack,
            side=side,
            start_coords=(int(start[0]), int(start[1])) if start else target_coords,
            target_coords=(int(target_coords[0]), int(target_coords[1])),
            major_objective_hexes=major_objective_hexes,
        )
        reinforcement_mobilization_bonus = self._reinforcement_mobilization_bonus(
            stack=stack,
            side=side,
            start_coords=(int(start[0]), int(start[1])) if start else target_coords,
            target_coords=(int(target_coords[0]), int(target_coords[1])),
        )
        island_exit_bonus = 0
        start_xy = (int(start[0]), int(start[1])) if start else (int(target_coords[0]), int(target_coords[1]))
        if has_ground and self._is_islanded_hex(start_xy):
            if self._friendly_ground_count_at_coords(start_xy, side) > 1 and tuple(start_xy) != tuple(target_coords):
                island_exit_bonus += 180

        capital_garrison_penalty = self._capital_garrison_vacate_penalty(stack, target_coords, side)

        relief_bonus = self._stack_relief_bonus(stack, target_coords, side)
        return int(
            progress_score
            + contact_score
            + risk
            + backtrack_penalty
            + revisit_penalty
            + efficiency_bonus
            + frontier_bonus
            + objective_entry_bonus
            + low_value_penalty
            + late_distance_penalty
            + posture_adjust
            + air_posture_adjust
            + air_support_bonus
            + transport_coordination_bonus
            + major_push_bonus
            + reinforcement_mobilization_bonus
            + island_exit_bonus
            + capital_garrison_penalty
            + relief_bonus
        )

    def _is_late_game(self) -> bool:
        end_turn = int(getattr(self.game_state.scenario_spec, "end_turn", 30) or 30)
        if end_turn <= 0:
            end_turn = 30
        current_turn = int(getattr(self.game_state, "turn", 1) or 1)
        return current_turn >= max(20, int(end_turn * 0.67))

    def _objective_urgency_multiplier(self) -> float:
        end_turn = int(getattr(self.game_state.scenario_spec, "end_turn", 30) or 30)
        if end_turn <= 0:
            return 1.0
        current_turn = int(getattr(self.game_state, "turn", 1) or 1)
        ratio = max(0.0, min(1.0, current_turn / end_turn))
        # Neutral most of the game, then steeply increases objective pressure near the end.
        return 1.0 + max(0.0, ratio - 0.6) * 1.5

    def _estimate_stack_move_cost(self, stack, target_coords: tuple[int, int]) -> float:
        if not stack:
            return 1.0
        sample = stack[0]
        start = getattr(sample, "position", None)
        if not start or start[0] is None:
            return 1.0
        if (int(start[0]), int(start[1])) == (int(target_coords[0]), int(target_coords[1])):
            return 0.0
        start_hex = Hex.offset_to_axial(start[0], start[1])
        target_hex = Hex.offset_to_axial(target_coords[0], target_coords[1])
        distance = max(1, int(start_hex.distance_to(target_hex)))
        try:
            direct_cost = self.game_state.map.get_movement_cost(sample, start_hex, target_hex)
            if isinstance(direct_cost, (int, float)) and direct_cost != float("inf") and direct_cost > 0:
                return float(max(1.0, direct_cost))
        except Exception:
            pass
        return float(distance)

    def _stack_role_weights(self, stack, side: str) -> dict[str, float]:
        has_fleet = any(u.is_fleet() for u in stack)
        has_wing = any(u.is_wing() for u in stack)
        has_army = any(u.is_army() for u in stack)
        profile = self._side_strategy_profile(side)
        posture = profile.get("posture", "balanced")
        if has_fleet and not has_army and not has_wing:
            return {"objective": 1.0, "threat": 1.1, "cohesion": 1.0}
        if has_wing and not has_army:
            # Air-only stacks should mostly support ground plans, except in escape scenarios.
            if posture == "escape":
                return {"objective": 1.0, "threat": 1.2, "cohesion": 0.9}
            return {"objective": 0.65, "threat": 0.95, "cohesion": 0.75}
        return {"objective": 1.2, "threat": 1.0, "cohesion": 1.15}

    def _air_support_mobility_bonus(
        self,
        stack,
        side: str,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
        objective_hexes: set[tuple[int, int]],
        has_air_only: bool,
    ) -> int:
        if not has_air_only:
            return 0
        if not stack:
            return 0
        start_obj_dist = self._min_distance_to_objectives(start_coords, objective_hexes)
        target_obj_dist = self._min_distance_to_objectives(target_coords, objective_hexes)
        start_ground_dist = self._nearest_friendly_ground_distance(start_coords, side)
        target_ground_dist = self._nearest_friendly_ground_distance(target_coords, side)
        carrying_escort = any(
            any(
                getattr(p, "is_on_map", False)
                and (
                    (hasattr(p, "is_army") and p.is_army())
                    or (hasattr(p, "is_leader") and p.is_leader())
                )
                for p in list(getattr(u, "passengers", []) or [])
            )
            for u in stack
        )
        bonus = 0
        if target_obj_dist < start_obj_dist:
            bonus += 70
        if target_ground_dist < start_ground_dist:
            bonus += 55
        if carrying_escort:
            bonus += 35
        if target_obj_dist >= 999 and target_ground_dist >= start_ground_dist:
            bonus -= 60
        return int(bonus)

    def _nearest_friendly_ground_distance(self, coords: tuple[int, int], side: str) -> int:
        src = Hex.offset_to_axial(coords[0], coords[1])
        best = 999
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != side:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            if not (hasattr(unit, "is_army") and unit.is_army()):
                continue
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None:
                continue
            d = src.distance_to(Hex.offset_to_axial(pos[0], pos[1]))
            if d < best:
                best = d
        return int(best)

    def _transport_coordination_bonus(
        self,
        stack,
        side: str,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
        objective_hexes: set[tuple[int, int]],
    ) -> int:
        if not stack:
            return 0
        bonus = 0
        has_fleet_only = self._is_fleet_only_stack(stack)
        has_ground = any(
            hasattr(u, "is_army")
            and u.is_army()
            and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            for u in stack
        )
        if has_ground and not has_fleet_only:
            start_dist = self._nearest_friendly_transport_distance(start_coords, side)
            target_dist = self._nearest_friendly_transport_distance(target_coords, side)
            if target_dist < start_dist:
                bonus += (start_dist - target_dist) * 75

        if self._is_empty_fleet_stack(stack):
            fleet = stack[0]
            pickup_hexes = self._friendly_transport_pickup_hexes(side, fleet)
            if pickup_hexes:
                start_pick = self._min_distance_to_points(start_coords, pickup_hexes)
                target_pick = self._min_distance_to_points(target_coords, pickup_hexes)
                if target_pick < start_pick:
                    bonus += (start_pick - target_pick) * 130

        if self._is_fleet_only_stack(stack) and any(self._fleet_has_ground_or_leader_passengers(f) for f in stack):
            fleet = stack[0]
            coast = self._objective_coast_hexes_for_fleet(fleet, objective_hexes)
            if coast:
                start_coast = self._min_distance_to_points(start_coords, coast)
                target_coast = self._min_distance_to_points(target_coords, coast)
                if target_coast < start_coast:
                    bonus += (start_coast - target_coast) * 85
        return int(bonus)

    def _nearest_friendly_transport_distance(self, coords: tuple[int, int], side: str) -> int:
        src = Hex.offset_to_axial(coords[0], coords[1])
        best = 999
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != side:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "unit_type", None) not in (UnitType.FLEET, UnitType.CITADEL):
                continue
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None:
                continue
            d = src.distance_to(Hex.offset_to_axial(pos[0], pos[1]))
            if d < best:
                best = d
        return int(best)

    def _is_fleet_only_stack(self, stack) -> bool:
        return bool(stack) and all(u.is_fleet() for u in stack)

    def _is_empty_fleet_stack(self, stack) -> bool:
        if not self._is_fleet_only_stack(stack):
            return False
        return not any(self._fleet_has_ground_or_leader_passengers(f) for f in stack)

    def _is_loaded_fleet_stack(self, stack) -> bool:
        if not self._is_fleet_only_stack(stack):
            return False
        return any(self._fleet_has_ground_or_leader_passengers(f) for f in stack)

    @staticmethod
    def _fleet_has_ground_or_leader_passengers(fleet) -> bool:
        passengers = list(getattr(fleet, "passengers", []) or [])
        return any(
            (hasattr(p, "is_army") and p.is_army())
            or (hasattr(p, "is_leader") and p.is_leader())
            for p in passengers
        )

    def _fleet_escape_only_objective_active(self, side: str) -> bool:
        for node in self._victory_nodes_for_side(side):
            ntype = str(node.get("type", "")).strip().lower()
            if ntype != "escape_unit_score":
                continue
            unit_type_raw = node.get("unit_type")
            if unit_type_raw is None:
                unit_type_raw = node.get("unit_types")
            if unit_type_raw is None:
                continue
            values = unit_type_raw if isinstance(unit_type_raw, (list, tuple, set)) else [unit_type_raw]
            normalized = {str(getattr(v, "value", v)).strip().lower() for v in values}
            if UnitType.FLEET.value in normalized or "fleet" in normalized:
                return True
        return False

    def _empty_fleet_move_is_transport_relevant(
        self,
        stack,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
        side: str,
        objective_hexes: set[tuple[int, int]],
    ) -> bool:
        if not stack:
            return False
        fleet = stack[0]
        pickup_hexes = self._friendly_transport_pickup_hexes(side, fleet)
        if not pickup_hexes:
            # Empty fleets without realistic pickup opportunities should hold position.
            return False
        start_pick = self._min_distance_to_points(start_coords, pickup_hexes)
        target_pick = self._min_distance_to_points(target_coords, pickup_hexes)
        return target_pick < start_pick and target_pick <= 4

    def _loaded_fleet_move_is_objective_relevant(
        self,
        stack,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
        objective_hexes: set[tuple[int, int]],
    ) -> bool:
        if not stack:
            return False
        fleet = stack[0]
        coast = self._objective_coast_hexes_for_fleet(fleet, objective_hexes)
        if not coast:
            return True
        start_dist = self._min_distance_to_points(start_coords, coast)
        target_dist = self._min_distance_to_points(target_coords, coast)
        return target_dist <= start_dist

    def _friendly_transport_pickup_hexes(self, side: str, fleet) -> set[tuple[int, int]]:
        out = set()
        for unit in self.game_state.units:
            if getattr(unit, "allegiance", None) != side:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            if not (hasattr(unit, "is_army") and unit.is_army()):
                continue
            if getattr(unit, "unit_type", None) in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL):
                continue
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None:
                continue
            hex_obj = Hex.offset_to_axial(pos[0], pos[1])
            try:
                if self.game_state.map.can_stack_move_to([fleet], hex_obj):
                    out.add((int(pos[0]), int(pos[1])))
            except Exception:
                continue
        return out

    def _objective_coast_hexes_for_fleet(self, fleet, objective_hexes: set[tuple[int, int]]) -> set[tuple[int, int]]:
        out = set()
        for coords in objective_hexes:
            center = Hex.offset_to_axial(coords[0], coords[1])
            candidates = [center] + list(center.neighbors())
            for hx in candidates:
                try:
                    if self.game_state.map.can_stack_move_to([fleet], hx):
                        out.add(tuple(hx.axial_to_offset()))
                except Exception:
                    continue
        return out

    def _min_distance_to_points(self, src: tuple[int, int], points: set[tuple[int, int]]) -> int:
        if not points:
            return 999
        return min(self._distance(src, p) for p in points)

    def _major_objective_push_bonus(
        self,
        stack,
        side: str,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
        major_objective_hexes: set[tuple[int, int]],
    ) -> int:
        profile = self._side_strategy_profile(side)
        if not profile.get("is_offensive", False):
            return 0
        if not major_objective_hexes:
            return 0
        start_dist = self._min_distance_to_objectives(start_coords, major_objective_hexes)
        target_dist = self._min_distance_to_objectives(target_coords, major_objective_hexes)
        if start_dist >= 999 or target_dist >= 999:
            return 0
        bonus = max(0, start_dist - target_dist) * 52
        if target_coords in major_objective_hexes and target_dist < start_dist:
            bonus += 140
        has_ground = any(
            hasattr(u, "is_army")
            and u.is_army()
            and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            for u in stack
        )
        if has_ground and target_dist <= 3:
            bonus += 40
        return int(bonus)

    def _reinforcement_mobilization_bonus(
        self,
        stack,
        side: str,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
    ) -> int:
        profile = self._side_strategy_profile(side)
        if not profile.get("is_offensive", False):
            return 0
        has_ground = any(
            hasattr(u, "is_army")
            and u.is_army()
            and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            for u in stack
        )
        if not has_ground:
            return 0
        start_hex = Hex.offset_to_axial(start_coords[0], start_coords[1])
        enemy_adj_start = self._adjacent_enemy_count(start_hex, side)
        if enemy_adj_start > 0:
            return 0
        start_enemy_dist = self._nearest_enemy_distance(start_coords, side)
        target_enemy_dist = self._nearest_enemy_distance(target_coords, side)
        if start_enemy_dist < 4:
            return 0
        if target_enemy_dist < start_enemy_dist:
            return int((start_enemy_dist - target_enemy_dist) * 65)
        return 0

    def _nearest_enemy_distance(self, coords: tuple[int, int], side: str) -> int:
        src = Hex.offset_to_axial(coords[0], coords[1])
        best = 999
        for unit in self.game_state.units:
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "allegiance", None) in (side, NEUTRAL, None):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None:
                continue
            d = src.distance_to(Hex.offset_to_axial(pos[0], pos[1]))
            if d < best:
                best = d
        return int(best)

    def _friendly_ground_count_at_hex(self, hex_obj: Hex, side: str) -> int:
        return sum(
            1
            for u in self.game_state.get_units_at(hex_obj)
            if getattr(u, "is_on_map", False)
            and getattr(u, "allegiance", None) == side
            and hasattr(u, "is_army")
            and u.is_army()
            and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            and getattr(u, "transport_host", None) is None
        )

    def _friendly_ground_count_at_coords(self, coords: tuple[int, int], side: str) -> int:
        return self._friendly_ground_count_at_hex(Hex.offset_to_axial(coords[0], coords[1]), side)

    def _is_islanded_hex(self, coords: tuple[int, int]) -> bool:
        center = Hex.offset_to_axial(coords[0], coords[1])
        for n in center.neighbors():
            col, row = n.axial_to_offset()
            if not self.game_state.is_hex_in_bounds(col, row):
                continue
            terrain = self.game_state.map.get_terrain(n)
            if terrain not in (TerrainType.OCEAN, TerrainType.MAELSTROM):
                return False
        return True

    def _should_attempt_unboard_at_hex(
        self,
        hex_obj: Hex,
        side: str,
        objective_hexes: set[tuple[int, int]],
        profile: dict[str, Any],
    ) -> bool:
        coords = tuple(hex_obj.axial_to_offset())
        target_in_objective = coords in objective_hexes
        enemy_here = any(
            getattr(u, "is_on_map", False)
            and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
            for u in self.game_state.get_units_at(hex_obj)
        )
        enemy_adj = self._adjacent_enemy_count(hex_obj, side)
        loc = self.game_state.map.get_location(hex_obj)
        enemy_location = bool(loc and getattr(loc, "occupier", None) not in (None, side, NEUTRAL))
        if target_in_objective or enemy_here or enemy_adj > 0 or enemy_location:
            return True
        if self._is_islanded_hex(coords):
            return True
        if profile.get("transport_campaign", False):
            # Allow stepping-stone unboards only near objective coast.
            return self._min_distance_to_objectives(coords, objective_hexes) <= 2
        return False

    def _required_ground_unboard_garrison(
        self,
        hex_obj: Hex,
        side: str,
        objective_hexes: set[tuple[int, int]],
        _profile: dict[str, Any],
    ) -> int:
        coords = tuple(hex_obj.axial_to_offset())
        if self._is_islanded_hex(coords):
            return 1
        enemy_adj = self._adjacent_enemy_count(hex_obj, side)
        need = 1
        if coords in objective_hexes and enemy_adj > 0:
            need = 2
        elif enemy_adj >= 2:
            need = 2
        return need

    def _violates_air_support_tether(
        self,
        stack,
        start_coords: tuple[int, int],
        target_coords: tuple[int, int],
        side: str,
        objective_hexes: set[tuple[int, int]],
    ) -> bool:
        if not stack:
            return False
        has_ground = any(getattr(u, "is_army", lambda: False)() for u in stack)
        has_air = any(getattr(u, "unit_type", None) in (UnitType.WING, UnitType.CITADEL) for u in stack)
        if not has_air or has_ground:
            return False
        profile = self._side_strategy_profile(side)
        if profile.get("victory_category") == "escape":
            return False
        carrying_escort = any(
            any(
                getattr(p, "is_on_map", False)
                and (
                    (hasattr(p, "is_army") and p.is_army())
                    or (hasattr(p, "is_leader") and p.is_leader())
                )
                for p in list(getattr(u, "passengers", []) or [])
            )
            for u in stack
        )
        if carrying_escort:
            return False

        start_ground = self._nearest_friendly_ground_distance(start_coords, side)
        target_ground = self._nearest_friendly_ground_distance(target_coords, side)
        if target_ground >= 999:
            return False
        target_hex = Hex.offset_to_axial(target_coords[0], target_coords[1])
        friendly_ground_adj = 0
        for n in target_hex.neighbors():
            for u in self.game_state.get_units_at(n):
                if getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) == side:
                    if u.is_army() and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL):
                        friendly_ground_adj += 1
        enemy_adj = self._adjacent_enemy_count(target_hex, side)
        # Hard rule: air-only stacks do not end adjacent to enemies without adjacent ground support.
        if enemy_adj > 0 and friendly_ground_adj <= 0:
            return True
        if target_coords in objective_hexes:
            enemy_here = any(
                getattr(u, "is_on_map", False)
                and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
                for u in self.game_state.get_units_at(target_hex)
            )
            if not enemy_here:
                return False
        max_dist = self.AI_AIR_TETHER_MAX_OFFENSIVE if profile.get("is_offensive", False) else self.AI_AIR_TETHER_MAX_DEFENSIVE
        if target_ground > max_dist and target_ground >= start_ground:
            return True

        enemies = [
            u
            for u in self.game_state.get_units_at(target_hex)
            if getattr(u, "is_on_map", False)
            and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
        ]
        if not enemies:
            return False

        # Hard attack gate for unsupported air-only stacks.
        if friendly_ground_adj <= 0 and target_ground > 2:
            return True
        if enemy_adj > 0 and friendly_ground_adj <= 0 and target_ground > 1:
            return True

        atk_cs = sum(int(getattr(u, "combat_rating", 0) or 0) for u in stack)
        def_cs = sum(int(getattr(u, "combat_rating", 0) or 0) for u in enemies)
        if atk_cs <= 0:
            return True
        odds = atk_cs / max(1, def_cs)
        if odds < 1.15 and target_ground > 1:
            return True
        if friendly_ground_adj <= 0 and odds < 1.35:
            return True
        if friendly_ground_adj > 0 and odds < 1.3:
            return True
        return False

    def _score_deployment_hex(self, unit, coords: tuple[int, int], objective_hexes: set[tuple[int, int]]) -> int:
        target_hex = Hex.offset_to_axial(coords[0], coords[1])
        side = getattr(unit, "allegiance", None)
        dist = self._min_distance_to_objectives(coords, objective_hexes)
        friendly_adj = self._adjacent_friendly_count(target_hex, side)
        enemy_adj = self._adjacent_enemy_count(target_hex, side)
        profile = self._side_strategy_profile(side)
        posture = profile.get("posture", "balanced")
        transport_campaign = bool(profile.get("transport_campaign", False))
        base = int((0 if dist >= 999 else -dist * 12) + friendly_adj * 10 - enemy_adj * 14)

        # Capital garrison priority: ensure at least one army in allied capitals.
        cap_bonus = self._capital_deployment_need_bonus(unit, coords, side)
        capital_overstack_penalty = self._offensive_capital_overstack_penalty(unit, coords, side)
        defense_bonus = self._hex_defense_value(coords)
        border_pressure = enemy_adj * 18

        if posture == "defensive":
            base += int(defense_bonus * 20 + border_pressure * 0.7)
            if enemy_adj == 0 and friendly_adj == 0:
                base -= 18
        elif posture == "offensive":
            base += int(border_pressure * 1.2)
            base += int(defense_bonus * 6)
            base += self._offensive_country_pressure_bonus(coords, side)
        elif posture == "escape":
            # Keep deployments cohesive and safer in escape scenarios.
            base += int(defense_bonus * 16 + friendly_adj * 8)
            if enemy_adj >= 2:
                base += 10

        # HL can activate + invade in control-style scenarios, so favor forward pressure.
        if side == HL and profile.get("control_focus", False):
            base += int(border_pressure * 0.5)
        if side == WS and profile.get("control_focus", False):
            # WS typically benefits from sturdier deployment.
            base += int(defense_bonus * 8)

        if getattr(unit, "unit_type", None) == UnitType.FLEET:
            target_hex_units = [
                u for u in self.game_state.get_units_at(target_hex)
                if getattr(u, "is_on_map", False) and getattr(u, "allegiance", None) == side
            ]
            fleets_here = sum(1 for u in target_hex_units if u.is_fleet())
            ground_here = sum(
                1
                for u in target_hex_units
                if hasattr(u, "is_army")
                and u.is_army()
                and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            )
            # Spread fleets by default; clustering is only good when coordinating immediate embarkation.
            base -= fleets_here * 220
            if transport_campaign:
                base += min(ground_here, 2) * 140
                coast = self._objective_coast_hexes_for_fleet(unit, objective_hexes)
                if coast:
                    sea_dist = self._min_distance_to_points(coords, coast)
                    if sea_dist < 999:
                        base += max(0, 70 - sea_dist * 10)

        if transport_campaign and hasattr(unit, "is_army") and unit.is_army() and getattr(unit, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL):
            nearest_transport = self._nearest_friendly_transport_distance(coords, side)
            if nearest_transport < 999:
                base += max(0, 95 - nearest_transport * 18)

        return int(base + cap_bonus + capital_overstack_penalty)

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
            fleet_attackers = [u for u in source_units if u.is_fleet()]

            for target_hex in source_hex.neighbors():
                defenders = [
                    u for u in self.game_state.get_units_at(target_hex)
                    if getattr(u, "is_on_map", False)
                    and getattr(u, "allegiance", None) not in (side, NEUTRAL, None)
                ]
                if not defenders:
                    continue

                if land_attackers:
                    if not self._combat_passes_hard_gates(land_attackers, defenders, target_hex, side):
                        score = -9999
                    else:
                        score = self._score_combat(land_attackers, defenders, target_hex, side, source_hex=source_hex)
                        if target_hex.axial_to_offset() in self._failed_combat_targets.get(side, set()):
                            score -= 700
                    candidates.append({"score": score, "attackers": list(land_attackers), "target_hex": target_hex})
                    evaluated += 1
                    if evaluated >= self.AI_MAX_COMBAT_EVAL:
                        break

                naval_ready = [f for f in fleet_attackers if self.game_state.can_fleet_attack_hex(f, target_hex)]
                if naval_ready:
                    if not self._combat_passes_hard_gates(naval_ready, defenders, target_hex, side):
                        score = -9999
                    else:
                        score = self._score_combat(naval_ready, defenders, target_hex, side, source_hex=source_hex)
                        if target_hex.axial_to_offset() in self._failed_combat_targets.get(side, set()):
                            score -= 700
                    candidates.append({"score": score, "attackers": list(naval_ready), "target_hex": target_hex})
                    evaluated += 1
                    if evaluated >= self.AI_MAX_COMBAT_EVAL:
                        break

        return candidates

    def _score_combat(self, attackers, defenders, target_hex: Hex, side: str, source_hex: Hex | None = None) -> int:
        att = sum(int(getattr(u, "combat_rating", 0) or 0) for u in attackers)
        deff_raw = sum(int(getattr(u, "combat_rating", 0) or 0) for u in defenders)
        deff = self._effective_defender_strength_for_ai(target_hex, deff_raw)
        odds = att / max(1, deff)
        material = (att - deff) * 12
        # Expected-value style term: prefer favorable odds, avoid low-odds trades.
        expected_trade = int((odds - 1.0) * 120)
        if odds < 0.85:
            expected_trade -= 120
        elif odds < 1.0:
            expected_trade -= 60

        objective_bonus = 0
        target_offset = target_hex.axial_to_offset()
        urgency = self._objective_urgency_multiplier()
        profile = self._side_strategy_profile(side)
        major_objectives = self._major_objective_hexes_for_side(side)
        if target_offset in self._objective_hexes_for_side(side):
            objective_bonus = max(objective_bonus, int(260 * urgency))
        if target_offset in major_objectives:
            objective_bonus = max(objective_bonus, int(360 * urgency))
        enemy_side = self.game_state.get_enemy_allegiance(side)
        if target_offset in self._objective_hexes_for_side(enemy_side):
            objective_bonus = max(objective_bonus, int(300 * urgency))

        posture_adjust = 0
        posture = profile.get("posture", "balanced")
        if posture == "defensive" and odds < 1.05:
            posture_adjust -= 60
        if posture == "offensive" and odds >= 1.0:
            posture_adjust += 35
        if posture == "escape" and odds < 1.2:
            posture_adjust -= 90

        drm_risk_penalty = int(abs(min(0, self._estimate_combat_drm_risk(attackers, defenders, target_hex, source_hex))) * 18)

        return material + expected_trade + objective_bonus + posture_adjust - drm_risk_penalty

    def _combat_passes_hard_gates(self, attackers, defenders, target_hex: Hex, side: str) -> bool:
        att = sum(int(getattr(u, "combat_rating", 0) or 0) for u in attackers)
        deff_raw = sum(int(getattr(u, "combat_rating", 0) or 0) for u in defenders)
        deff = self._effective_defender_strength_for_ai(target_hex, deff_raw)
        odds = att / max(1, deff)
        profile = self._side_strategy_profile(side)
        posture = profile.get("posture", "balanced")
        min_odds = 1.0
        if posture == "offensive":
            min_odds = 0.95
        elif posture == "defensive":
            min_odds = 1.15
        elif posture == "escape":
            min_odds = 1.25

        air_only_attack = bool(attackers) and all(
            getattr(u, "unit_type", None) in (UnitType.WING, UnitType.CITADEL)
            for u in attackers
        )
        if air_only_attack:
            src_pos = getattr(attackers[0], "position", None)
            src_coords = (int(src_pos[0]), int(src_pos[1])) if src_pos and src_pos[0] is not None else None
            support_dist = self._nearest_friendly_ground_distance(src_coords, side) if src_coords else 999
            target_obj = target_hex.axial_to_offset() in self._objective_hexes_for_side(side)
            if support_dist > 2:
                return False
            if support_dist > 1 and odds < 1.5:
                return False
            if not target_obj and odds < 1.35:
                return False

        if odds >= min_odds:
            return True
        if profile.get("is_offensive", False):
            if target_hex.axial_to_offset() in self._major_objective_hexes_for_side(side) and odds >= 0.9:
                return True
        # Critical late-turn push: allow sub-threshold attacks near key objectives.
        if odds < 0.85:
            return False
        if not self._is_late_game() or not self._is_critical_objective_push(target_hex, side):
            return False
        end_turn = int(getattr(self.game_state.scenario_spec, "end_turn", 30) or 30)
        current_turn = int(getattr(self.game_state, "turn", 1) or 1)
        return (end_turn - current_turn) <= 2

    def _is_critical_objective_push(self, target_hex: Hex, side: str) -> bool:
        target = target_hex.axial_to_offset()
        enemy_side = self.game_state.get_enemy_allegiance(side)
        return (
            target in self._objective_hexes_for_side(side)
            or target in self._objective_hexes_for_side(enemy_side)
        )

    def _effective_defender_strength_for_ai(self, target_hex: Hex, defender_cs: int) -> int:
        loc = self.game_state.map.get_location(target_hex) if self.game_state and self.game_state.map else None
        mult = 1
        if loc:
            loc_type = getattr(loc, "loc_type", None)
            if loc_type == LocType.FORTRESS.value:
                mult = 3
            elif loc_type in (LocType.CITY.value, LocType.PORT.value):
                mult = 2
        return int(defender_cs * mult)

    def _estimate_combat_drm_risk(self, attackers, defenders, target_hex: Hex, source_hex: Hex | None) -> int:
        drm = 0
        atk_leader = max(
            [int(getattr(u, "tactical_rating", 0) or 0) for u in attackers if hasattr(u, "is_leader") and u.is_leader()],
            default=0,
        )
        def_leader = max(
            [int(getattr(u, "tactical_rating", 0) or 0) for u in defenders if hasattr(u, "is_leader") and u.is_leader()],
            default=0,
        )
        drm += atk_leader - def_leader

        loc = self.game_state.map.get_location(target_hex) if self.game_state and self.game_state.map else None
        if loc:
            loc_type = getattr(loc, "loc_type", None)
            if loc_type == LocType.FORTRESS.value:
                drm -= 4
            elif loc_type in (LocType.CITY.value, LocType.PORT.value):
                drm -= 2
            elif loc_type == LocType.UNDERCITY.value:
                drm -= 10

        # If source is known and direct crossing exists, model harsh crossing penalties.
        if source_hex and self.game_state and self.game_state.map:
            hs = self.game_state.map.get_hexside(source_hex, target_hex)
            if hs == "river":
                drm -= 4
            elif hs == "bridge":
                drm -= 4
            elif hs == "ford":
                drm -= 3
            elif hs == "pass":
                drm -= 2

        return int(drm)

    def _side_strategy_profile(self, side: str) -> dict[str, Any]:
        cached = self._side_strategy_cache.get(side)
        if cached is not None:
            return cached

        nodes = self._victory_nodes_for_side(side)
        category = self._primary_victory_category(side)
        offensive_side = self._stance_offensive_side()
        enemy_side = self.game_state.get_enemy_allegiance(side)

        if category == "escape":
            posture = "escape"
        elif category == "survive":
            posture = "defensive"
        elif offensive_side in (HL, WS):
            posture = "offensive" if side == offensive_side else "defensive"
        else:
            posture = "offensive" if side == HL else "defensive"

        control_focus = any(
            str(node.get("type", "")).strip().lower() in {"conquer_country", "control_n_countries", "ally_country"}
            for node in nodes
        )
        target_countries = self._target_country_ids_for_side(side)
        transport_campaign = self._compute_transport_campaign_mode(side, posture, category, target_countries)
        profile = {
            "posture": posture,
            "is_offensive": posture == "offensive",
            "is_defensive": posture == "defensive",
            "victory_category": category,
            "enemy_victory_category": self._primary_victory_category(enemy_side),
            "offensive_side": offensive_side,
            "control_focus": bool(control_focus),
            "target_countries": target_countries,
            "transport_campaign": bool(transport_campaign),
        }
        self._side_strategy_cache[side] = profile
        return profile

    def _compute_transport_campaign_mode(
        self,
        side: str,
        posture: str,
        category: str,
        target_countries: set[str],
    ) -> bool:
        if posture != "offensive":
            return False
        if category not in {"conquer", "capture"}:
            return False
        if not target_countries:
            return False
        has_fleet = any(
            getattr(u, "allegiance", None) == side
            and u.is_fleet()
            and getattr(u, "status", None) in (UnitState.READY, UnitState.ACTIVE, UnitState.DEPLETED)
            for u in self.game_state.units
        )
        if not has_fleet:
            return False
        has_ground = any(
            getattr(u, "allegiance", None) == side
            and hasattr(u, "is_army")
            and u.is_army()
            and getattr(u, "unit_type", None) not in (UnitType.FLEET, UnitType.WING, UnitType.CITADEL)
            and getattr(u, "status", None) in (UnitState.READY, UnitState.ACTIVE, UnitState.DEPLETED)
            for u in self.game_state.units
        )
        if not has_ground:
            return False
        objective_hexes = self._objective_hexes_for_side(side)
        if not objective_hexes:
            return False
        # Maritime campaign hint: objective area has at least one fleet-accessible objective/coastal hex.
        for u in self.game_state.units:
            if getattr(u, "allegiance", None) != side or getattr(u, "unit_type", None) != UnitType.FLEET:
                continue
            coast = self._objective_coast_hexes_for_fleet(u, objective_hexes)
            if coast:
                return True
        return False

    def _transport_campaign_mode_active(self, side: str) -> bool:
        return bool(self._side_strategy_profile(side).get("transport_campaign", False))

    def _victory_nodes_for_side(self, side: str) -> list[dict[str, Any]]:
        vc = getattr(self.game_state.scenario_spec, "victory_conditions", {}) or {}
        side_vc = vc.get(side, {}) or {}
        nodes = []
        self._collect_victory_nodes(side_vc.get("major"), nodes)
        minor = side_vc.get("minor")
        if isinstance(minor, dict) and "conditions" in minor:
            for item in minor.get("conditions", []) or []:
                node = item.get("when") if isinstance(item, dict) and "when" in item else item
                self._collect_victory_nodes(node, nodes)
        else:
            self._collect_victory_nodes(minor, nodes)
        return nodes

    def _primary_victory_category(self, side: str) -> str:
        if side not in (HL, WS):
            return "control"
        nodes = self._victory_nodes_for_side(side)
        if not nodes:
            return "control"
        node_types = {str(node.get("type", "")).strip().lower() for node in nodes}
        # Matrix semantics: capture/conquer are explicitly offensive-driving categories.
        if "conquer_country" in node_types:
            return "conquer"
        if "capture_location" in node_types:
            return "capture"
        category_score = {
            "capture": 0,
            "conquer": 0,
            "control": 0,
            "destroy": 0,
            "prevent": 0,
            "escape": 0,
            "survive": 0,
        }
        for node in nodes:
            ntype = str(node.get("type", "")).strip().lower()
            if ntype == "capture_location":
                category_score["capture"] += 3
            elif ntype == "conquer_country":
                category_score["conquer"] += 4
            elif ntype in {"control_n_countries", "ally_country"}:
                category_score["control"] += 3
            elif ntype == "destroy_unit_score":
                category_score["destroy"] += 3
            elif ntype in {"prevent_location_captured", "prevent_country_conquered", "prevent_country_control"}:
                category_score["prevent"] += 4
            elif ntype == "escape_unit_score":
                category_score["escape"] += 5
            elif ntype == "survive_unit_score":
                category_score["survive"] += 5

        return max(category_score.keys(), key=lambda k: category_score[k])

    def _stance_offensive_side(self) -> str | None:
        hl_key = self._primary_victory_category(HL)
        ws_key = self._primary_victory_category(WS)
        row = self._ai_stance_matrix.get(hl_key, {})
        value = str(row.get(ws_key, "-")).strip().upper()
        if value in (HL, WS):
            return value
        return None

    def _collect_victory_nodes(self, node: Any, out: list[dict[str, Any]]):
        if node is None:
            return
        if isinstance(node, list):
            for child in node:
                self._collect_victory_nodes(child, out)
            return
        if not isinstance(node, dict):
            return
        if "all" in node:
            for child in node.get("all", []) or []:
                self._collect_victory_nodes(child, out)
            return
        if "any" in node:
            for child in node.get("any", []) or []:
                self._collect_victory_nodes(child, out)
            return
        if "type" in node:
            out.append(node)

    def _capital_deployment_need_bonus(self, unit, coords: tuple[int, int], side: str) -> int:
        if not hasattr(unit, "is_army") or not unit.is_army():
            return 0
        profile = self._side_strategy_profile(side)
        for country in self.game_state.countries.values():
            if getattr(country, "allegiance", None) != side:
                continue
            capital = getattr(country, "capital", None)
            if not capital or not getattr(capital, "coords", None):
                continue
            cap_coords = tuple(capital.coords)
            if cap_coords != tuple(coords):
                continue
            cap_hex = Hex.offset_to_axial(cap_coords[0], cap_coords[1])
            armies = [
                u
                for u in self.game_state.get_units_at(cap_hex)
                if getattr(u, "is_on_map", False)
                and getattr(u, "allegiance", None) == side
                and hasattr(u, "is_army")
                and u.is_army()
                and getattr(u, "transport_host", None) is None
            ]
            if not armies:
                return 180
            # Prefer keeping at least one weaker unit as garrison while stronger units move out.
            weakest = min(int(getattr(u, "combat_rating", 0) or 0) for u in armies)
            unit_power = int(getattr(unit, "combat_rating", 0) or 0)
            if profile.get("is_offensive", False):
                if unit_power <= weakest:
                    return 120
                return max(-40, 25 - unit_power * 8)
            if unit_power <= weakest:
                return 80
            return 35
        return 0

    def _offensive_capital_overstack_penalty(self, unit, coords: tuple[int, int], side: str) -> int:
        if not (hasattr(unit, "is_army") and unit.is_army()):
            return 0
        profile = self._side_strategy_profile(side)
        if not profile.get("is_offensive", False):
            return 0
        for country in self.game_state.countries.values():
            if getattr(country, "allegiance", None) != side:
                continue
            capital = getattr(country, "capital", None)
            if not capital or not getattr(capital, "coords", None):
                continue
            cap_coords = tuple(capital.coords)
            if tuple(coords) != cap_coords:
                continue
            cap_hex = Hex.offset_to_axial(cap_coords[0], cap_coords[1])
            armies_here = [
                u
                for u in self.game_state.get_units_at(cap_hex)
                if getattr(u, "is_on_map", False)
                and getattr(u, "allegiance", None) == side
                and hasattr(u, "is_army")
                and u.is_army()
                and getattr(u, "transport_host", None) is None
            ]
            if len(armies_here) <= 0:
                return 0
            # Offensive posture: keep only one garrison army in capitals.
            unit_power = int(getattr(unit, "combat_rating", 0) or 0)
            return -900 - unit_power * 30
        return 0

    def _hex_defense_value(self, coords: tuple[int, int]) -> float:
        hex_obj = Hex.offset_to_axial(coords[0], coords[1])
        score = 0.0
        terrain = self.game_state.map.get_terrain(hex_obj)
        if terrain in (TerrainType.FOREST, TerrainType.MOUNTAIN, TerrainType.SWAMP):
            score += 1.0
        loc = self.game_state.map.get_location(hex_obj)
        if loc:
            if loc.loc_type in (LocType.FORTRESS.value, LocType.UNDERCITY.value):
                score += 2.0
            elif loc.loc_type in (LocType.CITY.value, LocType.PORT.value):
                score += 1.2
        # Natural barriers: reward border tiles that are harder to cross.
        for neighbor in hex_obj.neighbors():
            hs = self.game_state.map.get_hexside(hex_obj, neighbor)
            if hs in ("river", "deep_river", "mountain", "sea"):
                score += 0.25
        return score

    def _offensive_country_pressure_bonus(self, coords: tuple[int, int], side: str) -> int:
        profile = self._side_strategy_profile(side)
        targets = set(profile.get("target_countries") or [])
        if not targets:
            return 0
        best = 0
        src = Hex.offset_to_axial(coords[0], coords[1])
        for cid in targets:
            country = self.game_state.countries.get(cid)
            if not country:
                continue
            locs = [loc for loc in country.locations.values() if getattr(loc, "coords", None)]
            if not locs:
                continue
            min_dist = min(src.distance_to(Hex.offset_to_axial(loc.coords[0], loc.coords[1])) for loc in locs)
            avg_def = sum(self._location_defense_value(loc) for loc in locs) / max(1, len(locs))
            fragility = max(0.0, 4.0 - avg_def) + (1.5 if len(locs) <= 2 else 0.0)
            score = int(max(0, 40 - min_dist * 7) + fragility * 12)
            best = max(best, score)
        return best

    @staticmethod
    def _location_defense_value(loc) -> float:
        loc_type = getattr(loc, "loc_type", None)
        if loc_type == LocType.FORTRESS.value:
            return 4.0
        if loc_type == LocType.UNDERCITY.value:
            return 6.0
        if loc_type in (LocType.CITY.value, LocType.PORT.value):
            return 2.5
        return 1.0

    def _capital_garrison_vacate_penalty(self, stack, target_coords: tuple[int, int], side: str) -> int:
        if not stack:
            return 0
        start = getattr(stack[0], "position", None)
        if not start or start[0] is None:
            return 0
        start_xy = (int(start[0]), int(start[1]))
        target_xy = (int(target_coords[0]), int(target_coords[1]))
        if start_xy == target_xy:
            return 0
        if self._would_leave_capital_undefended_after_departure(start_xy, stack, side):
            return -self.AI_CAPITAL_GARRISON_VACATE_PENALTY
        return 0

    def _resolve_ai_leader_escapes(self, resolution: dict[str, Any] | None):
        if not resolution:
            return
        requests = resolution.get("leader_escape_requests") or []
        for req in requests:
            leader = getattr(req, "leader", None)
            options = getattr(req, "options", None) or []
            if not leader or not options:
                continue
            player = self.game_state.get_player(getattr(leader, "allegiance", None))
            if not (player and player.is_ai):
                continue
            destination = self.game_state._get_leader_escape_handler().choose_escape_destination(leader, options)
            if destination is None:
                continue
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

    def _major_objective_hexes_for_side(self, side: str) -> set[tuple[int, int]]:
        out = set()
        vc = getattr(self.game_state.scenario_spec, "victory_conditions", {}) or {}
        side_vc = vc.get(side, {}) or {}
        self._collect_objective_hexes(side_vc.get("major"), out)
        return out

    def _target_country_ids_for_side(self, side: str) -> set[str]:
        out = set()
        for node in self._victory_nodes_for_side(side):
            ntype = str(node.get("type", "")).strip().lower()
            if ntype in {"conquer_country", "prevent_country_conquered", "ally_country", "prevent_country_control"}:
                cid = str(node.get("country", "")).strip().lower()
                if cid:
                    out.add(cid)
            if ntype == "capture_location":
                loc_id = str(node.get("location", "")).strip().lower()
                if not loc_id:
                    continue
                for country in self.game_state.countries.values():
                    if loc_id in (country.locations or {}):
                        out.add(str(country.id).strip().lower())
                        break
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
        invasion_data = self.movement_service.get_invasion_force(country_id)
        if invasion_data.get("strength", 0) <= 0:
            return -9999

        success_prob = self._estimate_invasion_success_likelihood(country_id, side)
        activation_score = success_prob * 150
        strength_score = 50 if success_prob > 0.8 else 0
        strategic_score = self._country_objective_relevance(side, country_id) * 60
        engagement_penalty = self._current_engagement_penalty(side)
        border_bonus = self._border_presence_bonus(country_id, side) * 10
        profile = self._side_strategy_profile(side)
        posture_bonus = 40 if profile.get("is_offensive", False) else -50

        return int(activation_score + strength_score + strategic_score - engagement_penalty + border_bonus + posture_bonus)

    def _estimate_invasion_success_likelihood(self, country_id: str, side: str) -> float:
        """Estimate likelihood of successful invasion based on military balance."""
        country = self.game_state.countries.get(country_id)
        if not country:
            return 0.0
        
        invasion_data = self.movement_service.get_invasion_force(country_id)
        invader_sp = invasion_data.get("strength", 0)
        if invader_sp <= 0:
            return 0.0
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
