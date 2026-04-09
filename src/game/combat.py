import os
import random

from game.unit import Unit
from src.content.config import CRT_DATA
from src.content.specs import HexsideType, LocType, TerrainType, UnitRace, UnitState, UnitType
from src.content.constants import HL, MIN_COMBAT_ROLL, MAX_COMBAT_ROLL, NEUTRAL, WS
from src.content.loader import load_data
from src.content.tools import TextFormatter, caption_id
from src.game.combat_reporting import show_combat_result_popup
from src.game.leader_escape import LeaderEscapeCheck, LeaderEscapeHandler, LeaderEscapeRequest
from src.game.map import Hex

# This module is intentionally rule-dense: it centralizes combat math, special-case
# rule handling, and click-driven combat UX orchestration in one place.


def apply_dragon_orb_bonus(attackers, defenders, consume_asset_fn, damage_unit_fn, roll_d6_fn=None):
    """
    Resolves Dragon Orb usage before normal land combat.

    Trigger condition per side:
    - Side has a leader equipped with dragon_orb
    - Opposing force includes at least one DRAGON or DRACONIAN unit
    """
    roll_d6 = roll_d6_fn or (lambda: random.randint(1, 6))
    logs = []

    for side_name, friendly, opposing in (
        ("attacker", attackers, defenders),
        ("defender", defenders, attackers),
    ):
        if not any(unit.is_draconid() for unit in opposing):
            continue

        orb_users = []
        for unit in friendly:
            if not (hasattr(unit, "is_leader") and unit.is_leader() and unit.is_on_map):
                continue
            orb = _get_equipped_asset(unit, "dragon_orb")
            if orb:
                orb_users.append((unit, orb))

        for leader, orb in orb_users:
            if not leader.is_on_map:
                continue
            roll = roll_d6()
            tactical_rating = int(getattr(leader, "tactical_rating", 0) or 0)
            if roll > tactical_rating:
                damage_unit_fn(leader, mode="destroy")
                consume_asset_fn(orb, leader)
                logs.append(
                    f"Dragon Orb ({side_name}) failed: {leader.id} rolled {roll} > TR {tactical_rating}; leader and orb destroyed."
                )
                continue

            destroyed_dragons = []
            for enemy in opposing:
                if not (enemy.is_on_map and enemy.is_dragon()):
                    continue
                damage_unit_fn(enemy, mode="destroy")
                destroyed_dragons.append(enemy)
            consume_asset_fn(orb, leader)
            logs.append(
                f"Dragon Orb ({side_name}) succeeded: {leader.id} rolled {roll} <= TR {tactical_rating}; destroyed {len(destroyed_dragons)} dragon unit(s)."
            )

    return logs


def apply_gnome_tech_bonus(
    attackers,
    defenders,
    consume_asset_fn,
    decide_use_fn=None,
    roll_d6_fn=None,
):
    """
    Resolves gnome_tech usage before land combat.

    Per side with at least one eligible equipped army:
    - optional use (random by default)
    - roll 2d6
      - non-doubles: attacker +max(dice), defender -max(dice)
      - doubles: attacker -6, defender +6 and tech is destroyed
    """
    roll_d6 = roll_d6_fn or (lambda: random.randint(1, 6))
    decide_use = decide_use_fn or (lambda _unit, _side: random.choice([True, False]))
    drm_bonus = {"attacker": 0, "defender": 0}
    logs = []

    for side_name, friendly in (("attacker", attackers), ("defender", defenders)):
        carrier = None
        tech = None
        for unit in friendly:
            if not unit.is_army() and unit.is_on_map:
                continue
            found = _get_equipped_asset_with_other(unit, "gnome_tech")
            if found is None:
                continue
            carrier = unit
            tech = found
            break

        if not carrier or not tech:
            continue
        if not decide_use(carrier, side_name):
            logs.append(f"Gnome tech ({side_name}) not used by {carrier.id}.")
            continue

        d1 = roll_d6()
        d2 = roll_d6()
        doubles = d1 == d2
        highest = max(d1, d2)

        if side_name == "attacker":
            delta = -6 if doubles else highest
        else:
            delta = 6 if doubles else -highest

        drm_bonus[side_name] += delta
        if doubles:
            consume_asset_fn(tech, carrier)
            logs.append(
                f"Gnome tech ({side_name}) doubles {d1}/{d2}: DRM {delta:+d}; tech destroyed."
            )
        else:
            logs.append(
                f"Gnome tech ({side_name}) roll {d1}/{d2}: DRM {delta:+d}."
            )

    return drm_bonus, logs


def _get_equipped_asset(unit, asset_id: str):
    """Returns the asset with the given ID equipped by the unit, or None if not found."""
    for asset in getattr(unit, "equipment", []) or []:
        if getattr(asset, "id", None) == asset_id:
            return asset
    return None


def _get_equipped_asset_with_other(unit, bonus_name: str):
    """
    Returns the first asset equipped by the unit that has a bonus.other matching the given name, or None if not found.
    """
    for asset in getattr(unit, "equipment", []) or []:
        bonus = getattr(asset, "bonus", None)
        if isinstance(bonus, dict) and bonus.get("other") == bonus_name:
            return asset
    return None


class CombatResolver:
    """
    Handles resolution of Land and Air combat according to Rule 7 (DL_11).
    """
    def __init__(
        self,
        attackers,
        defenders,
        terrain_type,
        game_state=None,
        consume_asset_fn=None,
        get_valid_retreat_hexes_fn=None,
        move_unit_fn=None,
        precombat_drm_bonus=0,
        allow_consumable_other_bonus=False,
    ):
        self.attackers = attackers
        self.defenders = defenders
        self.terrain_type = terrain_type
        self.game_state = game_state
        self._consume_asset_fn = consume_asset_fn
        self._get_valid_retreat_hexes_fn = get_valid_retreat_hexes_fn
        self._move_unit_fn = move_unit_fn
        self.precombat_drm_bonus = int(precombat_drm_bonus or 0)
        self.allow_consumable_other_bonus = bool(allow_consumable_other_bonus)
        # Use the centralized loader
        self.crt_data = load_data(CRT_DATA) # csv or yaml?

    def calculate_odds(self, attacker_cs: float, defender_cs: float) -> str:
        """
        Calculates the odds of a combat based on the attacker's combat rating and the defender's combat rating.
        Rule 7.2: Minimum 1/3 odds, Maximum 6/1 odds logic

        Returns:
            str: The odds string in the format "X:Y" where X is the attacker's odds and Y is the defender's odds.
        """
        if defender_cs <= 0: return "6:1"
        ratio = attacker_cs / defender_cs

        # Logic to map ratio to CRT columns (rounding in favor of defender)
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

    def calculate_effective_combat_strengths(self):
        """Returns effective attacker and defender combat strengths for this combat context."""
        attacker_cs = sum(u.combat_rating for u in self.attackers)
        defender_cs = sum(u.combat_rating for u in self.defenders)
        defender_cs *= self._get_defender_combat_multiplier()
        return attacker_cs, defender_cs

    def _damage_unit(self, unit, mode: str = "deplete"):
        self.game_state.damage_unit(unit, mode=mode)

    def resolve(self):
        # Core land/air resolution pipeline:
        # odds -> DRM -> die roll (+DRM clamp) -> CRT lookup -> apply both sides.
        # 1. Calculate Odds
        attacker_cs, defender_cs = self.calculate_effective_combat_strengths()
        
        odds_str = self.calculate_odds(attacker_cs, defender_cs)
        
        # 2. Determine DRMs (Leader Tactical Ratings, Terrain, etc.)
        drm, drm_parts = self.calculate_total_drm(return_breakdown=True)

        # 3. Roll 1d10
        roll = random.randint(1, 10)

        # min -5, max 16
        final_roll = max(MIN_COMBAT_ROLL, min(MAX_COMBAT_ROLL, roll + drm))

        # 4. Look up result from CRT data
        result = self.crt_data[final_roll][odds_str]
        parts_text = ", ".join(f"{name}={value:+d}" for name, value in drm_parts if value)
        if not parts_text:
            parts_text = "none"
        print(f"Combat odds: attacker_cs={attacker_cs} defender_cs={defender_cs} -> {odds_str}")
        print(f"Combat DRM: total={drm:+d} [{parts_text}]")
        print(f"Combat roll: d10={roll} + drm={drm:+d} -> final={final_roll} => result={result}")

        self.apply_results(result, self.attackers, True)
        self.apply_results(result, self.defenders, False)

        return result

    def apply_results(self, result_code, units, is_attacker):
        """
        Apply combat results to the given units.

        units: list of Unit objects in the hex
        combat_result: string like "DR", "2/E", "E/1", etc.
        is_attacker: True if applying to attacker's units
        """
        must_retreat = False

        # Parse combat result (e.g., "D1", "2/E", or "-/DR")
        if is_attacker:
            result = result_code.split('/')[0]
        else:
            result = result_code.split('/')[1]

        # Handle "No Effect" result
        if result == '-':
            return

        if 'R' in result:
            must_retreat = True

        apply_deplete_all = 'D' in result
        apply_eliminate_all = 'E' in result
        depletion_steps = sum(int(ch) for ch in result if ch.isdigit())

        affected = self._get_affected_armies(units)

        if apply_eliminate_all:
            for unit in affected:
                self._damage_unit(unit, mode="eliminate")
        elif apply_deplete_all:
            for unit in affected:
                self._damage_unit(unit, mode="deplete")

        if depletion_steps:
            self._apply_depletion_steps(affected, depletion_steps)

        if must_retreat and not (not is_attacker and self._defender_ignores_retreat()):
            self._apply_retreats(affected)

        if not (apply_eliminate_all or apply_deplete_all or depletion_steps or must_retreat):
            error_msg = f"Invalid combat result: {result_code}"
            raise ValueError(error_msg)

    def calculate_total_drm(self, return_breakdown=False):
        """
        Calculate the total DRM for the combat, including leader tactical ratings, terrain effects, crossing penalties,
        and other bonuses.
        DRMs are accumulated as signed parts so callers can show a transparent breakdown in logs/UI while still using
        a single integer total.
        """
        drm = 0
        breakdown = []
        def add_part(label, value):
            nonlocal drm
            value = int(value or 0)
            drm += value
            breakdown.append((label, value))

        defender_hex = self._get_defender_hex()
        defender_terrain = self._effective_defender_terrain()
        defender_location = self._get_defender_location()
        defender_loc_type = self._normalize_loc_type(defender_location)

        # LEADERS
        atk_leader = sum( u.tactical_rating for u in self.attackers if u.is_leader() )
        def_leader = sum( u.tactical_rating for u in self.defenders if u.is_leader() )
        add_part("attacker_leader", atk_leader)
        add_part("defender_leader", -def_leader)

        # DRAGONS (Dragon wings only)
        attacker_dragon_bonus = sum(
            u.combat_rating
            for u in self.attackers
            if u.is_wing() and u.is_dragon()
        )
        if self._defender_has_other_bonus("dragon_slayer") and attacker_dragon_bonus:
            attacker_dragon_bonus = 0
            self._consume_other_bonus_if_needed(self.defenders, "dragon_slayer")
        add_part("attacker_dragons", attacker_dragon_bonus)

        defender_dragon_bonus = sum(
            u.combat_rating
            for u in self.defenders
            if u.is_wing() and u.is_dragon()
        )
        add_part("defender_dragons", -defender_dragon_bonus)

        # ARMOR: defender stack forces attacker -1 DRM
        if self._defender_has_other_bonus("armor"):
            add_part("defender_armor", -1)
            self._consume_other_bonus_if_needed(self.defenders, "armor")

        # CAVALRY (+1 attacker only, not vs location/forest/jungle)
        cavalry_blocked = bool(defender_location) or defender_terrain in (TerrainType.FOREST, TerrainType.JUNGLE)
        if not cavalry_blocked and any(u.unit_type == UnitType.CAVALRY for u in self.attackers):
            add_part("attacker_cavalry", 1)

        # FLIGHT (+1 attacker if has fliers, -1 defender if has fliers)
        flight_blocked = (
            defender_loc_type == LocType.UNDERCITY.value
            or defender_terrain in (TerrainType.FOREST, TerrainType.MOUNTAIN, TerrainType.JUNGLE)
        )
        if not flight_blocked:
            if any(u.is_flier() for u in self.attackers):
                add_part("attacker_fliers", 1)
            if any(u.is_flier() for u in self.defenders):
                add_part("defender_fliers", -1)

        # LOCATIONS (defender benefit only)
        if defender_loc_type == LocType.FORTRESS.value:
            add_part("location_fortress", -4)
        elif defender_loc_type in (LocType.CITY.value, LocType.PORT.value, LocType.TEMPLE.value):
            add_part("location_city_port", -2)
        elif defender_loc_type == LocType.UNDERCITY.value:
            add_part("location_undercity", -10)

        # CROSSINGS: apply exactly one crossing DRM (the single worst among participating ground attackers)
        crossing_label, crossing_drm = self._resolve_worst_attacker_crossing(defender_hex)
        if crossing_label and crossing_drm:
            add_part(crossing_label, crossing_drm)

        # TERRAIN AFFINITY
        add_part("attacker_terrain_affinity", self._count_attacker_terrain_affinity_bonus())
        add_part("defender_terrain_affinity", -self._count_defender_terrain_affinity_bonus(defender_hex))

        # EVENT COMBAT BONUS (active player, current battle turn only)
        if self.game_state and hasattr(self.game_state, "get_combat_bonus"):
            active_player = getattr(self.game_state, "active_player", None)
            if active_player and any(getattr(u, "allegiance", None) == active_player for u in self.attackers):
                add_part("event_combat_bonus", int(self.game_state.get_combat_bonus(active_player)))

        add_part("precombat_drm_bonus", self.precombat_drm_bonus)
        if return_breakdown:
            return drm, breakdown
        return drm

    def _get_defender_hex(self):
        if not self.game_state or not self.game_state.map:
            return None
        for unit in self.defenders:
            if not unit.position:
                continue
            col, row = unit.position
            if col is None or row is None:
                continue
            from src.game.map import Hex
            return Hex.offset_to_axial(col, row)
        return None

    def _get_defender_location(self):
        # Citadel-vs-WS special case can suppress defender location benefits.
        if self._citadel_attack_strips_ws_defender_bonuses():
            return None
        if self._attacking_air_against_citadel():
            # Air attacking a citadel is treated like city defense for modifiers.
            return {"type": LocType.CITY.value}

        defender_hex = self._get_defender_hex()
        if not defender_hex or not self.game_state or not self.game_state.map:
            return None
        return self.game_state.map.get_location(defender_hex)

    def _get_defender_combat_multiplier(self):
        if self._citadel_attack_strips_ws_defender_bonuses():
            return 1

        loc = self._get_defender_location()
        loc_type = self._normalize_loc_type(loc)
        if loc_type == LocType.FORTRESS.value:
            return 3
        if loc_type in (LocType.CITY.value, LocType.PORT.value):
            return 2
        return 1

    def _defender_ignores_retreat(self):
        if self._citadel_attack_strips_ws_defender_bonuses():
            return False
        return bool(self._get_defender_location())

    def _defenders_include_citadel(self):
        return any(u.is_citadel() and u.is_on_map for u in self.defenders)

    def _attacking_air_against_citadel(self):
        if not self._defenders_include_citadel():
            return False
        return any(u.is_flier() for u in self.attackers if u.is_on_map)

    def _citadel_attack_strips_ws_defender_bonuses(self):
        attacker_has_citadel = any(
            u.is_citadel() and u.is_on_map
            for u in self.attackers
        )
        if not attacker_has_citadel:
            return False
        return any(
            u.allegiance == WS
            and u.is_army()
            and u.is_on_map
            for u in self.defenders
        )

    def _effective_defender_terrain(self):
        if self._citadel_attack_strips_ws_defender_bonuses():
            return TerrainType.GRASSLAND
        return self.terrain_type

    def _unit_has_other_bonus(self, unit, bonus_name):
        return _get_equipped_asset_with_other(unit, bonus_name) is not None

    def _defender_has_other_bonus(self, bonus_name):
        for unit in self.defenders:
            if not unit.is_on_map:
                continue
            if self._unit_has_other_bonus(unit, bonus_name):
                return True
        return False

    def _consume_other_bonus_if_needed(self, units, bonus_name):
        if not self.allow_consumable_other_bonus:
            return
        if not callable(self._consume_asset_fn):
            return
        for unit in units:
            asset = _get_equipped_asset_with_other(unit, bonus_name)
            if asset is None:
                continue
            if not getattr(asset, "is_consumable", False):
                continue
            self._consume_asset_fn(asset, unit)
            return

    def _collect_attacker_crossing_candidates(self, defender_hex):
        candidates = []
        if not defender_hex or not self.game_state or not self.game_state.map:
            return candidates
        for unit in self.attackers:
            if not unit.is_army():
                continue
            if not unit.position:
                continue
            col, row = unit.position
            if col is None or row is None:
                continue
            from src.game.map import Hex
            attacker_hex = Hex.offset_to_axial(col, row)
            if attacker_hex == defender_hex:
                continue
            if defender_hex not in attacker_hex.neighbors():
                continue

            if self.game_state.map.is_ship_bridge(attacker_hex, defender_hex, unit.allegiance):
                # Ship bridge is treated as bridge crossing DRM.
                candidates.append(("crossing_bridge", -4))
                continue

            hexside = self.game_state.map.get_effective_hexside(attacker_hex, defender_hex)
            if hexside in (
                HexsideType.RIVER,
                HexsideType.DEEP_RIVER,
            ):
                candidates.append(("crossing_river", -4))
            elif hexside == HexsideType.BRIDGE:
                candidates.append(("crossing_bridge", -4))
            elif hexside == HexsideType.FORD:
                candidates.append(("crossing_ford", -3))
            elif hexside == HexsideType.PASS:
                candidates.append(("crossing_pass", -2))
        return candidates

    def _resolve_worst_attacker_crossing(self, defender_hex):
        candidates = self._collect_attacker_crossing_candidates(defender_hex)
        if not candidates:
            return None, 0
        # Apply only one crossing DRM: the harshest applicable among attackers.
        # Tie-break keeps deterministic behavior when penalties are equal.
        tie_priority = {
            "crossing_river": 4,
            "crossing_bridge": 3,
            "crossing_ford": 2,
            "crossing_pass": 1,
        }
        return min(candidates, key=lambda item: (item[1], -tie_priority.get(item[0], 0)))

    def _normalize_loc_type(self, loc):
        if not loc:
            return None
        if hasattr(loc, "loc_type"):
            value = loc.loc_type
        elif isinstance(loc, dict):
            value = loc.get("type")
        else:
            return None
        if isinstance(value, LocType):
            return value.value
        return value

    def _count_attacker_terrain_affinity_bonus(self):
        if not self.game_state or not self.game_state.map:
            return 0
        bonus = 0
        from src.game.map import Hex
        for unit in self.attackers:
            if not (hasattr(unit, "is_army") and unit.is_army()):
                continue
            if not getattr(unit, "position", None):
                continue
            col, row = unit.position
            if col is None or row is None:
                continue
            terrain = self.game_state.map.get_terrain(Hex.offset_to_axial(col, row))
            if getattr(unit, "terrain_affinity", None) == terrain:
                bonus += 1
        return bonus

    def _count_defender_terrain_affinity_bonus(self, defender_hex):
        if not self.game_state or not self.game_state.map or not defender_hex:
            return 0
        terrain = self.game_state.map.get_terrain(defender_hex)
        bonus = 0
        for unit in self.defenders:
            if not unit.is_army():
                continue
            if getattr(unit, "terrain_affinity", None) == terrain:
                bonus += 1
        return bonus

    def _get_affected_armies(self, units):
        affected = []
        for unit in units:
            if not unit.is_on_map:
                continue
            if unit.is_control_unit():
                affected.append(unit)
        return affected

    def _apply_depletion_steps(self, units, steps):
        for _ in range(steps):
            ground_active = [u for u in units if u.status.name == "ACTIVE" and not u.is_wing()]
            if ground_active:
                target = min(ground_active, key=lambda u: u.combat_rating)
                self._damage_unit(target, mode="deplete")
                continue

            ground_depleted = [u for u in units if u.status.name == "DEPLETED" and not u.is_wing()]
            if ground_depleted:
                target = min(ground_depleted, key=lambda u: u.combat_rating)
                self._damage_unit(target, mode="eliminate")
                continue

            wing_active = [u for u in units if u.status.name == "ACTIVE" and u.is_flier()]
            if wing_active:
                target = min(wing_active, key=lambda u: u.combat_rating)
                self._damage_unit(target, mode="deplete")
                continue

            wing_depleted = [u for u in units if u.status.name == "DEPLETED" and u.is_flier()]
            if wing_depleted:
                target = min(wing_depleted, key=lambda u: u.combat_rating)
                self._damage_unit(target, mode="eliminate")
                continue

            break

    def _apply_retreats(self, units):
        if not self.game_state or not self.game_state.map:
            return
        if not callable(self._get_valid_retreat_hexes_fn) or not callable(self._move_unit_fn):
            return

        from src.game.map import Hex

        for unit in units:
            if not unit.position or unit.position[0] is None or unit.position[1] is None:
                continue
            start_hex = Hex.offset_to_axial(*unit.position)
            valid_hexes = self._get_valid_retreat_hexes_fn(unit, start_hex)
            if not valid_hexes:
                self._damage_unit(unit, mode="eliminate")
                continue
            retreat_hex = random.choice(valid_hexes)
            self._move_unit_fn(unit, retreat_hex)


class NavalCombatResolver:
    """
    Resolves Rule 8 fleet-to-fleet combat.
    """
    def __init__(self, game_state, attackers, defenders, roll_d10_fn=None, roll_d6_fn=None):
        self.game_state = game_state
        self.attackers = [u for u in attackers if u.is_fleet() and u.is_on_map]
        self.defenders = [u for u in defenders if u.is_fleet() and u.is_on_map]
        self._roll_d10 = roll_d10_fn or (lambda: random.randint(1, 10))
        self._roll_d6 = roll_d6_fn or (lambda: random.randint(1, 6))
        self._leader_escape_handler = LeaderEscapeHandler(game_state, roll_d6_fn=self._roll_d6)

    def resolve(self, withdraw_decider=None):
        rounds = 0
        while self.attackers and self.defenders:
            rounds += 1
            atk_round = [u for u in self.attackers if u.is_on_map]
            def_round = [u for u in self.defenders if u.is_on_map]
            if not atk_round or not def_round:
                break

            hits = {}
            for ship in atk_round:
                target = self._select_target(ship, def_round)
                if target is None:
                    continue
                if self._roll_hits(ship):
                    hits[target] = hits.get(target, 0) + 1

            for ship in def_round:
                target = self._select_target(ship, atk_round)
                if target is None:
                    continue
                if self._roll_hits(ship):
                    hits[target] = hits.get(target, 0) + 1

            for target, amount in hits.items():
                for _ in range(amount):
                    if not target.is_on_map:
                        break
                    if target.status == UnitState.ACTIVE:
                        self.game_state.damage_unit(target, mode="deplete")
                        continue
                    if target.status == UnitState.DEPLETED:
                        self.game_state.damage_unit(target, mode="eliminate")

            self._sync_combat_lists()
            if not self.attackers or not self.defenders:
                break

            if withdraw_decider and withdraw_decider(self._defender_side(), rounds):
                self._withdraw_all(self.defenders)
                break
            if withdraw_decider and withdraw_decider(self._attacker_side(), rounds):
                self._withdraw_all(self.attackers)
                break

        result = self._result_code()
        return {
            "result": result,
            "rounds": rounds,
            "attacker_survivors": len([u for u in self.attackers if u.is_on_map]),
            "defender_survivors": len([u for u in self.defenders if u.is_on_map]),
        }

    def _roll_hits(self, fleet):
        threshold = self._fleet_attack_rating(fleet)
        roll = self._roll_d10()
        return roll <= threshold

    def _fleet_attack_rating(self, fleet):
        base = fleet.combat_rating
        passengers = list(getattr(fleet, "passengers", []) or [])
        leader_bonus = 0
        for p in passengers:
            if not p.is_leader():
                continue
            leader_bonus = max(leader_bonus, getattr(p, "tactical_rating", 0))
        return base + leader_bonus

    def _select_target(self, attacker, candidates):
        live = [u for u in candidates if u.is_on_map]
        if not live:
            return None
        live.sort(key=lambda u: (0 if u.status.name == "DEPLETED" else 1, getattr(u, "combat_rating", 0)))
        return live[0]

    def _withdraw_all(self, side_fleets):
        for fleet in list(side_fleets):
            if not fleet.is_on_map or not fleet.position or None in fleet.position:
                continue
            from src.game.map import Hex
            start_hex = Hex.offset_to_axial(*fleet.position)
            state = (start_hex, getattr(fleet, "river_hexside", None))
            neighbors = self.game_state.map._fleet_neighbor_states(fleet, state)
            if not neighbors:
                continue
            next_hex, next_side = neighbors[0][0]
            self.game_state.move_unit(fleet, next_hex)
            fleet.river_hexside = next_side

    def _sync_combat_lists(self):
        self.attackers = [u for u in self.attackers if u.is_on_map]
        self.defenders = [u for u in self.defenders if u.is_on_map]

    def _result_code(self):
        if self.attackers and not self.defenders:
            return "N/NS"
        if self.defenders and not self.attackers:
            return "NS/N"
        if not self.attackers and not self.defenders:
            return "NS/NS"
        return "-/-"

    def _attacker_side(self):
        if self.attackers:
            return self.attackers[0].allegiance
        return None

    def _defender_side(self):
        if self.defenders:
            return self.defenders[0].allegiance
        return None


class DragonDuelResolver:
    """
    Resolves dragon-vs-dragon air supremacy duels before land combat.

    Each side rolls one d6 per current dragon combat point; 4+ scores one hit.
    Hits are applied to opposing dragons similarly to naval losses:
    ACTIVE -> DEPLETED -> DESTROYED.
    """
    def __init__(self, game_state, attacker_dragons, defender_dragons, roll_d6_fn=None):
        self.game_state = game_state
        self.attackers = list(attacker_dragons)
        self.defenders = list(defender_dragons)
        self._roll_d6 = roll_d6_fn or (lambda: random.randint(1, 6))

    def resolve(self, withdraw_decider=None):
        rounds = 0
        attacker_withdrew = False
        defender_withdrew = False

        while self.attackers and self.defenders:
            rounds += 1
            if rounds > 20:
                break
            atk_round = [u for u in self.attackers if u.is_on_map]
            def_round = [u for u in self.defenders if u.is_on_map]
            if not atk_round or not def_round:
                break

            hits = {}
            for dragon in atk_round:
                target = self._select_target(def_round)
                if target is None:
                    continue
                if self._roll_hits(dragon):
                    hits[target] = hits.get(target, 0) + 1

            for dragon in def_round:
                target = self._select_target(atk_round)
                if target is None:
                    continue
                if self._roll_hits(dragon):
                    hits[target] = hits.get(target, 0) + 1

            for target, amount in hits.items():
                for _ in range(amount):
                    if not target.is_on_map:
                        break
                    if target.status.name == "ACTIVE":
                        self.game_state.damage_unit(target, mode="deplete")
                        continue
                    if target.status.name == "DEPLETED":
                        self.game_state.damage_unit(target, mode="destroy")

            self._sync_combat_lists()
            if not self.attackers or not self.defenders:
                break

            if withdraw_decider and withdraw_decider(self._attacker_side(), rounds):
                self._withdraw_all(self.attackers)
                attacker_withdrew = True
                self._sync_combat_lists()
            if withdraw_decider and self.defenders and withdraw_decider(self._defender_side(), rounds):
                self._withdraw_all(self.defenders)
                defender_withdrew = True
                self._sync_combat_lists()
            if attacker_withdrew or defender_withdrew:
                break
            if not hits and not withdraw_decider:
                break

        return {
            "rounds": rounds,
            "attacker_withdrew": attacker_withdrew,
            "defender_withdrew": defender_withdrew,
            "attacker_survivors": len([u for u in self.attackers if u.is_on_map]),
            "defender_survivors": len([u for u in self.defenders if u.is_on_map]),
        }

    def _roll_hits(self, dragon):
        points = max(0, int(getattr(dragon, "combat_rating", 0) or 0))
        for _ in range(points):
            if self._roll_d6() >= 4:
                return True
        return False

    def _select_target(self, candidates):
        live = [u for u in candidates if u.is_on_map]
        if not live:
            return None
        live.sort(key=lambda u: (0 if u.status.name == "DEPLETED" else 1, getattr(u, "combat_rating", 0)))
        return live[0]

    def _withdraw_all(self, side_dragons):
        for dragon in list(side_dragons):
            if not dragon.is_on_map:
                continue
            self._withdraw_dragon_random_distance(dragon)

    def _withdraw_dragon_random_distance(self, dragon):
        if not self.game_state or not getattr(self.game_state, "map", None):
            return
        if not dragon.position or None in dragon.position:
            return
        from src.game.map import Hex
        start_hex = Hex.offset_to_axial(*dragon.position)
        max_distance = random.randint(1, 16)

        candidates = []
        frontier = [start_hex]
        visited = {start_hex}
        distance = {start_hex: 0}

        while frontier:
            current = frontier.pop(0)
            depth = distance[current]
            if depth >= max_distance:
                continue
            for nxt in current.neighbors():
                if nxt in visited:
                    continue
                visited.add(nxt)
                distance[nxt] = depth + 1
                frontier.append(nxt)

                col, row = nxt.axial_to_offset()
                if not self.game_state.is_hex_in_bounds(col, row):
                    continue
                if not self.game_state.map.can_unit_land_on_hex(dragon, nxt):
                    continue
                if self.game_state.map.has_enemy_army(nxt, dragon.allegiance):
                    continue
                if not self.game_state.map.can_stack_move_to([dragon], nxt):
                    continue
                if distance[nxt] >= 1:
                    candidates.append((distance[nxt], nxt))

        if not candidates:
            return

        candidates.sort(key=lambda item: item[0])
        farthest_distance = candidates[-1][0]
        pool = [h for d, h in candidates if d == farthest_distance]
        retreat_hex = random.choice(pool)
        self.game_state.move_unit(dragon, retreat_hex)

    def _sync_combat_lists(self):
        self.attackers = [u for u in self.attackers if u.is_on_map]
        self.defenders = [u for u in self.defenders if u.is_on_map]

    def _attacker_side(self):
        if self.attackers:
            return self.attackers[0].allegiance
        return None

    def _defender_side(self):
        if self.defenders:
            return self.defenders[0].allegiance
        return None


class CombatService:
    """
    Combat domain entry point. Callers should use this service instead of GameState directly.
    """

    def __init__(self, game_state):
        self.game_state = game_state

    @property
    def map(self):
        return self.game_state.map

    @property
    def units(self):
        return self.game_state.units

    @property
    def players(self):
        return self.game_state.players

    @property
    def active_player(self):
        return self.game_state.active_player

    @property
    def movement_service(self):
        return self.game_state.movement_service

    def is_hex_in_bounds(self, q: int, r: int) -> bool:
        return self.game_state.is_hex_in_bounds(q, r)

    def can_units_attack_target_hex(self, attackers, target_hex) -> bool:
        return self.game_state.can_units_attack_target_hex(attackers, target_hex)

    def _project_combat_odds(self, attackers, defenders, hex_position):
        terrain = self.game_state.map.get_terrain(hex_position)
        resolver = CombatResolver(attackers, defenders, terrain, game_state=self.game_state)
        attacker_cs, defender_cs = resolver.calculate_effective_combat_strengths()
        odds_str = resolver.calculate_odds(attacker_cs, defender_cs)
        ratio = float("inf") if defender_cs <= 0 else (attacker_cs / defender_cs)
        return {
            "attacker_cs": attacker_cs,
            "defender_cs": defender_cs,
            "odds_str": odds_str,
            "ratio": ratio,
        }

    def calculate_odds_preview(self, attackers, defenders, hex_position):
        """Helper to get odds column string (for example, '3:1') without rolling."""
        return self._project_combat_odds(attackers, defenders, hex_position)["odds_str"]

    def calculate_odds_ratio(self, attackers, defenders, hex_position):
        """Returns effective attacker/defender combat ratio for the given combat context."""
        return self._project_combat_odds(attackers, defenders, hex_position)["ratio"]

    def resolve_combat(
        self,
        attackers,
        hex_position,
        naval_withdraw_decider=None,
        dragon_duel_withdraw_decider=None,
        defenders_override=None,
    ):
        attackers = list(attackers)
        defender_pool = set(defenders_override) if defenders_override is not None else None

        def current_defenders():
            defenders_now = list(self.game_state.get_units_at(hex_position))
            if defender_pool is None:
                return defenders_now
            return [u for u in defenders_now if u in defender_pool]

        defenders = current_defenders()
        terrain = self.map.get_terrain(hex_position)
        defender_allegiances = {
            u.allegiance for u in defenders
            if u.allegiance not in (NEUTRAL, None)
        }

        if self._is_leader_only_stack(defenders) and self._attack_triggers_leader_stack_escape(attackers):
            leader_origins = {
                u: Hex.offset_to_axial(*u.position)
                for u in defenders
                if u.is_leader() and u.position and None not in u.position
            }
            leader_stack_has_army = {leader: True for leader in leader_origins.keys()}
            leader_escape_requests = self._resolve_leader_escapes(leader_origins, leader_stack_has_army)
            result = "-/-"
            print(TextFormatter.format_combat_log(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": leader_escape_requests or [],
                "advance_available": False,
            }

        if self._combat_blocked_by_citadel_rule(attackers, defenders):
            result = "-/-"
            print(TextFormatter.format_combat_log(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }
        attackers = self._filter_ws_ground_attackers_vs_citadel(attackers, defenders)
        if not self.can_units_attack_stack(attackers, defenders, target_hex=hex_position):
            result = "-/-"
            print(TextFormatter.format_combat_log(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }
        if not attackers:
            result = "-/-"
            print(TextFormatter.format_combat_log(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }

        if self._is_naval_combat(attackers, defenders):
            naval_resolver = NavalCombatResolver(self.game_state, attackers, defenders)
            outcome = naval_resolver.resolve(withdraw_decider=naval_withdraw_decider)
            self.cleanup_destroyed_units(attackers + defenders)
            print(TextFormatter.format_naval_log(attackers, defenders, outcome))
            return {
                "result": outcome.get("result", "-/-"),
                "leader_escape_requests": [],
                "advance_available": False,
                "combat_type": "naval",
                "rounds": outcome.get("rounds", 0),
            }

        for msg in self._apply_combat_healing(attackers + defenders):
            print(msg)
        orb_events = apply_dragon_orb_bonus(
            attackers,
            defenders,
            consume_asset_fn=self._consume_asset,
            damage_unit_fn=self.game_state.damage_unit,
        )
        if orb_events:
            self.cleanup_destroyed_units(attackers + defenders)
            attackers = [u for u in attackers if u.is_on_map]
            defenders = current_defenders()
            for evt in orb_events:
                print(evt)

            if not any(u.is_combat_unit() for u in defenders):
                result = "-/-"
                advance_available = self._can_advance_after_combat(
                    attackers=attackers,
                    target_hex=hex_position,
                    defender_allegiances=defender_allegiances,
                    attacker_had_to_retreat=False,
                )
                print(TextFormatter.format_combat_log(attackers, defenders, result))
                return {
                    "result": result,
                    "leader_escape_requests": [],
                    "advance_available": advance_available,
                }
            if not any(u.is_combat_unit() for u in attackers):
                result = "-/-"
                print(TextFormatter.format_combat_log(attackers, defenders, result))
                return {
                    "result": result,
                    "leader_escape_requests": [],
                    "advance_available": False,
                }

        attacker_dragons = [u for u in attackers if u.is_on_map and u.is_dragon()]
        defender_dragons = [u for u in defenders if u.is_on_map and u.is_dragon()]
        if attacker_dragons and defender_dragons:
            duel = DragonDuelResolver(self.game_state, attacker_dragons, defender_dragons)
            duel_outcome = duel.resolve(withdraw_decider=dragon_duel_withdraw_decider)
            print(
                f"Dragon duel after {duel_outcome.get('rounds', 0)} rounds: "
                f"A={duel_outcome.get('attacker_survivors', 0)} D={duel_outcome.get('defender_survivors', 0)}"
            )
            self.cleanup_destroyed_units(attackers + defenders)
            attackers = [u for u in attackers if u.is_on_map]
            defenders = current_defenders()
            if not any(u.is_combat_unit() for u in defenders):
                result = "-/-"
                advance_available = self._can_advance_after_combat(
                    attackers=attackers,
                    target_hex=hex_position,
                    defender_allegiances=defender_allegiances,
                    attacker_had_to_retreat=False,
                )
                print(TextFormatter.format_combat_log(attackers, defenders, result))
                return {
                    "result": result,
                    "leader_escape_requests": [],
                    "advance_available": advance_available,
                }

        attackers = self._filter_dragons_for_land_attack(attackers, defenders)
        if not any(u.is_combat_unit() for u in attackers):
            result = "-/-"
            print(TextFormatter.format_combat_log(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }

        gnome_drm = 0
        gnome_effects, gnome_logs = apply_gnome_tech_bonus(
            attackers,
            defenders,
            consume_asset_fn=self._consume_asset,
        )
        for msg in gnome_logs:
            print(msg)
        gnome_drm += int(gnome_effects.get("attacker", 0))
        gnome_drm += int(gnome_effects.get("defender", 0))

        special_retreat = self._apply_precombat_special_retreat(attackers, defenders, hex_position)
        if special_retreat["applied"]:
            self.cleanup_destroyed_units(defenders)
            defenders = current_defenders()
            if not any(u.is_combat_unit() for u in defenders):
                result = special_retreat["result"]
                leader_escape_requests = special_retreat.get("leader_escape_requests", []) or []
                advance_available = self._can_advance_after_combat(
                    attackers=attackers,
                    target_hex=hex_position,
                    defender_allegiances=defender_allegiances,
                    attacker_had_to_retreat=False,
                )
                print(TextFormatter.format_combat_log(attackers, defenders, result))
                return {
                    "result": result,
                    "leader_escape_requests": leader_escape_requests,
                    "advance_available": advance_available,
                }

        leader_origins = {}
        leader_stack_has_army = {}
        for unit in attackers + defenders:
            if unit.is_leader() and unit.position:
                origin_hex = Hex.offset_to_axial(*unit.position)
                leader_origins[unit] = origin_hex
                units_in_hex = self.map.get_units_in_hex(origin_hex.q, origin_hex.r)
                leader_stack_has_army[unit] = any(
                    u.allegiance == unit.allegiance and u.is_combat_unit()
                    for u in units_in_hex
                )

        resolver = CombatResolver(
            attackers,
            defenders,
            terrain,
            game_state=self.game_state,
            consume_asset_fn=self._consume_asset,
            get_valid_retreat_hexes_fn=self._get_valid_retreat_hexes,
            move_unit_fn=self.game_state.move_unit,
            precombat_drm_bonus=gnome_drm,
            allow_consumable_other_bonus=True,
        )
        result = resolver.resolve()
        print(f"Combat at Hex ({hex_position})")
        print(TextFormatter.format_combat_log(attackers, defenders, result))
        self.cleanup_destroyed_units(attackers + defenders)
        revive_escape_requests = self._resolve_leader_revives(attackers + defenders, leader_origins)
        leader_escape_requests = self._resolve_leader_escapes(leader_origins, leader_stack_has_army)
        leader_escape_requests = (revive_escape_requests or []) + (leader_escape_requests or [])

        attacker_result_code = result.split('/')[0] if '/' in result else result
        attacker_had_to_retreat = 'R' in attacker_result_code
        advance_available = self._can_advance_after_combat(
            attackers=attackers,
            target_hex=hex_position,
            defender_allegiances=defender_allegiances,
            attacker_had_to_retreat=attacker_had_to_retreat,
        )

        return {
            "result": result,
            "leader_escape_requests": leader_escape_requests or [],
            "advance_available": advance_available,
        }

    def _apply_combat_healing(self, units):
        logs = []
        for unit in units:
            if unit.status != UnitState.DEPLETED:
                continue
            if getattr(unit, "_healed_this_combat_turn", False):
                continue
            healing_asset = self._get_equipped_other_bonus_asset(unit, "healing")
            if healing_asset is None:
                continue
            unit.status = UnitState.ACTIVE
            unit._healed_this_combat_turn = True
            logs.append(f"Healing activated: {TextFormatter.format_unit_log_string(unit)} restored to ACTIVE.")
            if getattr(healing_asset, "is_consumable", False):
                self._consume_asset(healing_asset, unit)
                logs.append(f"Healing asset consumed: {healing_asset.id} on {TextFormatter.format_unit_log_string(unit)}.")
        return logs

    def _get_equipped_other_bonus_asset(self, unit, bonus_name):
        for asset in getattr(unit, "equipment", []) or []:
            bonus = getattr(asset, "bonus", None)
            if isinstance(bonus, dict) and bonus.get("other") == bonus_name:
                return asset
        return None

    def _resolve_leader_revives(self, units, leader_origins):
        requests = []
        for leader in units:
            if not leader.is_leader():
                continue
            if leader.status != UnitState.DESTROYED:
                continue
            revive_asset = self._get_equipped_other_bonus_asset(leader, "revive")
            if revive_asset is None:
                continue
            origin_hex = leader_origins.get(leader)
            if not origin_hex:
                continue
            options = self._get_nearest_friendly_combat_stacks(leader, origin_hex)
            if not options:
                continue

            leader.status = UnitState.ACTIVE
            leader.position = (None, None)
            requests.append(LeaderEscapeRequest(leader=leader, options=options))
            print(f"Revive activated: {leader.id} may escape to nearest friendly stack.")
            if getattr(revive_asset, "is_consumable", False):
                self._consume_asset(revive_asset, leader)
        return requests

    def _consume_asset(self, asset, unit):
        if hasattr(asset, "remove_from"):
            asset.remove_from(unit)
        else:
            if hasattr(unit, "equipment") and asset in unit.equipment:
                unit.equipment.remove(asset)
            asset.assigned_to = None

        if getattr(asset, "owner", None) and hasattr(asset.owner, "assets"):
            asset.owner.assets.pop(asset.id, None)
            return

        for player in self.players.values():
            if not hasattr(player, "assets"):
                continue
            candidate = player.assets.get(getattr(asset, "id", None))
            if candidate is asset or (candidate and getattr(candidate, "id", None) == getattr(asset, "id", None)):
                player.assets.pop(asset.id, None)
                return

    def can_units_attack_stack(self, attackers, defenders, target_hex=None):
        attackers = [u for u in attackers if u.is_on_map]
        defenders = [u for u in defenders if u.is_on_map]
        if not attackers or not defenders:
            return False

        if target_hex is None:
            for d in defenders:
                if getattr(d, "position", None) and d.position[0] is not None and d.position[1] is not None:
                    target_hex = Hex.offset_to_axial(*d.position)
                    break
        if target_hex and not self.can_units_attack_target_hex(attackers, target_hex):
            return False

        defenders_have_dragons = any(u.is_on_map and u.is_dragon() for u in defenders)
        for unit in attackers:
            if not unit.is_combat_unit():
                continue
            if not unit.is_dragon():
                return True
            if defenders_have_dragons:
                return True
            if self._dragon_can_make_ground_attack(unit, attackers):
                return True
        return False

    def _filter_dragons_for_land_attack(self, attackers, defenders):
        filtered = []
        for unit in attackers:
            if not unit.is_on_map:
                continue
            if not unit.is_dragon() or self._dragon_can_make_ground_attack(unit, attackers):
                filtered.append(unit)
        return filtered

    def _dragon_can_make_ground_attack(self, dragon, attackers):
        if not dragon.is_dragon():
            return True

        if dragon.allegiance == HL and self._all_highlords_destroyed():
            return False
        if dragon.allegiance == WS and self._all_ws_dragon_commanders_destroyed():
            return False

        return self._dragon_has_local_attack_leader(dragon, attackers)

    def _dragon_has_local_attack_leader(self, dragon, attackers):
        local_leaders = []
        for unit in attackers:
            if not unit.is_leader():
                continue
            if unit.allegiance != dragon.allegiance:
                continue
            if getattr(unit, "position", None) != getattr(dragon, "position", None):
                continue
            local_leaders.append(unit)

        for p in list(getattr(dragon, "passengers", []) or []):
            if p.is_leader() and p.allegiance == dragon.allegiance:
                local_leaders.append(p)

        if dragon.allegiance == HL:
            return any(self._is_valid_hl_dragon_commander(leader, dragon) for leader in local_leaders)
        if dragon.allegiance == WS:
            return any(self._is_valid_ws_dragon_commander(leader) for leader in local_leaders)
        return False

    def _is_valid_hl_dragon_commander(self, leader, dragon):
        if leader.unit_type == UnitType.EMPEROR:
            return True
        if leader.unit_type != UnitType.HIGHLORD:
            return False
        leader_flight = getattr(getattr(leader, "spec", None), "dragonflight", None)
        dragon_flight = getattr(getattr(dragon, "spec", None), "dragonflight", None)
        return bool(leader_flight and dragon_flight and leader_flight == dragon_flight)

    def _is_valid_ws_dragon_commander(self, leader):
        return leader.race in (UnitRace.SOLAMNIC, UnitRace.ELF)

    def _all_highlords_destroyed(self):
        highlords = [u for u in self.units if getattr(u, "unit_type", None) == UnitType.HIGHLORD]
        return bool(highlords) and all(getattr(u, "status", None) == UnitState.DESTROYED for u in highlords)

    def _all_ws_dragon_commanders_destroyed(self):
        ws_commanders = [
            u for u in self.units
            if u.allegiance == WS
            and u.is_leader()
            and u.race in (UnitRace.SOLAMNIC, UnitRace.ELF)
        ]
        return bool(ws_commanders) and all(u.status == UnitState.DESTROYED for u in ws_commanders)

    def _maybe_promote_highlord_to_emperor(self):
        living_emperors = [
            u for u in self.units
            if u.unit_type == UnitType.EMPEROR
            and u.status != UnitState.DESTROYED
        ]
        if living_emperors:
            return None

        candidates = [
            u for u in self.units
            if u.unit_type == UnitType.HIGHLORD
            and u.status != UnitState.DESTROYED
        ]
        if not candidates:
            return None

        promoted = random.choice(candidates)
        promoted._unit_type_override = UnitType.EMPEROR
        self._notify_emperor_promotion(promoted)
        return promoted

    def _notify_emperor_promotion(self, promoted):
        msg = f"{caption_id(promoted.id)} has been promoted to Emperor."
        print(msg)
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        if self.game_state.are_all_players_ai():
            return
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                QMessageBox.information(None, "Highlord Command", msg)
        except Exception:
            pass

    def _is_naval_combat(self, attackers, defenders):
        atk_fleets = [u for u in attackers if u.is_fleet() and u.is_on_map]
        if not atk_fleets or len(atk_fleets) != len([u for u in attackers if u.is_on_map]):
            return False
        def_fleets = [u for u in defenders if u.is_fleet() and u.is_on_map and u.allegiance != self.active_player]
        return bool(def_fleets)

    def _fleet_attack_nodes(self, fleet):
        if not fleet.position or None in fleet.position:
            return []
        nodes = []
        start_hex = Hex.offset_to_axial(*fleet.position)
        nodes.append(start_hex)
        river_side = getattr(fleet, "river_hexside", None)
        if river_side:
            endpoints = self.map._river_endpoints_local(river_side)
            for ep in endpoints:
                if ep not in nodes:
                    nodes.append(ep)
        return nodes

    def _fleets_are_adjacent_for_combat(self, attacker_fleet, defender_fleet):
        """
        Determines if two fleets are adjacent for combat purposes, which includes being in the same hex
        or in neighboring hexes.
        """
        attacker_nodes = self._fleet_attack_nodes(attacker_fleet)
        defender_nodes = self._fleet_attack_nodes(defender_fleet)
        if not attacker_nodes or not defender_nodes:
            return False
        for a in attacker_nodes:
            for d in defender_nodes:
                if a == d:
                    return True
                if d in a.neighbors():
                    return True
        return False

    def can_fleet_attack_hex(self, fleet, target_hex):
        """
        Determines if a fleet can attack a given hex, which requires at least one enemy fleet in the target hex that
        is adjacent for combat.
        """
        if not fleet.is_fleet() or not fleet.is_on_map:
            return False
        defenders = [
            u for u in self.game_state.get_units_at(target_hex)
            if u.is_fleet()
            and u.allegiance != fleet.allegiance
            and u.allegiance != NEUTRAL
            and u.is_on_map
        ]
        if not defenders:
            return False
        return any(self._fleets_are_adjacent_for_combat(fleet, d) for d in defenders)

    def _apply_precombat_special_retreat(self, attackers, defenders, target_hex):
        """
        Applies special retreat rules that can trigger before combat rolls, such as Wing/Cavalry escaping slower units.
        """
        combat_defenders = [
            u for u in defenders
            if u.is_on_map
            and u.position and None not in u.position
            and u.is_combat_unit()
        ]
        if not combat_defenders:
            return {"applied": False, "result": None, "leader_escape_requests": []}

        if self.map.get_location(target_hex):
            return {"applied": False, "result": None, "leader_escape_requests": []}

        combat_attackers = [
            u for u in attackers
            if u.is_on_map
            and u.position and None not in u.position
            and u.is_combat_unit()
        ]
        if not combat_attackers:
            return {"applied": False, "result": None, "leader_escape_requests": []}

        if any(u.unit_type not in (UnitType.WING, UnitType.CAVALRY) for u in combat_defenders):
            return {"applied": False, "result": None, "leader_escape_requests": []}

        attacker_has_wing = any(u.is_wing() for u in combat_attackers)
        attacker_has_cavalry = any(u.unit_type == UnitType.CAVALRY for u in combat_attackers)

        wing_rule = not attacker_has_wing
        cavalry_rule = not attacker_has_wing and not attacker_has_cavalry
        if not (wing_rule or cavalry_rule):
            return {"applied": False, "result": None, "leader_escape_requests": []}

        leader_escape_requests = []
        for unit in combat_defenders:
            leader_escape_requests.extend(self._retreat_single_unit(unit) or [])

        result = "-/SRC" if cavalry_rule else "-/SRW"
        return {"applied": True, "result": result, "leader_escape_requests": leader_escape_requests}

    def _retreat_single_unit(self, unit):
        """
        Handles retreat logic for a single unit, including forced boarding of leaders onto Wings and escape rolls
        for leaders who can't board.
        """
        if not unit.position or unit.position[0] is None or unit.position[1] is None:
            return []
        status_before = unit.status
        start_hex = Hex.offset_to_axial(*unit.position)
        valid_hexes = self._get_valid_retreat_hexes(unit, start_hex)
        if not valid_hexes:
            self.game_state.damage_unit(unit, mode="eliminate")
            return []

        leaders_here = [
            u for u in self.game_state.get_units_at(start_hex)
            if u.is_on_map
            and u.is_leader()
            and u.allegiance == unit.allegiance
            and u.transport_host is None
        ]

        retreat_hex = random.choice(valid_hexes)

        leader_escape_requests = []
        boarded_leaders = set()

        if unit.is_wing():
            for leader in leaders_here:
                can_land = (
                    self.map.can_unit_land_on_hex(leader, retreat_hex)
                    and self.map.can_stack_move_to([leader], retreat_hex)
                    and not self.map.has_enemy_army(retreat_hex, leader.allegiance)
                )
                if can_land:
                    continue
                if self._force_board_leader_for_retreat(unit, leader):
                    boarded_leaders.add(id(leader))
                    continue
                request = self._resolve_single_leader_escape_roll(leader, start_hex)
                if request:
                    leader_escape_requests.append(request)

        self.game_state.move_unit(unit, retreat_hex)
        if unit.is_on_map:
            unit.status = status_before

        for leader in leaders_here:
            if id(leader) in boarded_leaders:
                continue
            if leader.status == UnitState.DESTROYED:
                continue
            if leader.transport_host is not None:
                continue

            can_land = (
                self.map.can_unit_land_on_hex(leader, retreat_hex)
                and self.map.can_stack_move_to([leader], retreat_hex)
                and not self.map.has_enemy_army(retreat_hex, leader.allegiance)
            )
            if can_land:
                leader_status = leader.status
                self.game_state.move_unit(leader, retreat_hex)
                if leader.is_on_map:
                    leader.status = leader_status
                continue

            request = self._resolve_single_leader_escape_roll(leader, start_hex)
            if request:
                leader_escape_requests.append(request)

        return leader_escape_requests

    def _force_board_leader_for_retreat(self, wing, leader):
        if not wing or not leader:
            return False
        if not wing.is_wing() or not leader.is_leader():
            return False
        if not wing.position or not leader.position or wing.position != leader.position:
            return False
        if leader.transport_host is not None:
            return True
        if not wing.can_carry(leader):
            return False

        self.map.remove_unit_from_spatial_map(leader)
        wing.load_unit(leader)
        leader.position = wing.position
        leader.is_transported = True
        leader.transport_host = wing
        self.movement_service.normalize_transport_state()
        return True

    def _resolve_single_leader_escape_roll(self, leader, origin_hex):
        requests = self.game_state._get_leader_escape_handler().handle_leader_escapes(
            [
                LeaderEscapeCheck(
                    leader=leader,
                    origin_hex=origin_hex,
                    allow_fleet_destinations=False,
                    roll_required=True,
                    require_prior_combat_stack=False,
                    skip_if_allied_combat_present=False,
                    auto_place_on_success=False,
                )
            ],
            auto_resolve_ai=True,
        )
        return requests[0] if requests else None

    def _get_valid_retreat_hexes(self, unit, start_hex):
        valid = []
        for neighbor in start_hex.neighbors():
            col, row = neighbor.axial_to_offset()
            if not self.is_hex_in_bounds(col, row):
                continue
            if not self.map.can_unit_land_on_hex(unit, neighbor):
                continue
            if self.map.has_enemy_army(neighbor, unit.allegiance):
                continue
            if not self.map.can_stack_move_to([unit], neighbor):
                continue

            cost = self.map.get_movement_cost(unit, start_hex, neighbor)
            if cost == float('inf') or cost is None:
                continue

            friendly_present = any(
                u.allegiance == unit.allegiance and u.is_control_unit()
                for u in self.map.get_units_in_hex(neighbor.q, neighbor.r)
            )
            if not friendly_present and self.map.is_adjacent_to_enemy(neighbor, unit):
                continue

            valid.append(neighbor)
        return valid

    def _can_advance_after_combat(self, attackers, target_hex, defender_allegiances, attacker_had_to_retreat) -> bool:
        if attacker_had_to_retreat:
            return False
        if not defender_allegiances:
            return False

        target_offset = target_hex.axial_to_offset()
        remaining_defender_combat_units = [
            u for u in self.map.get_units_in_hex(target_hex.q, target_hex.r)
            if u.is_on_map
            and u.position == target_offset
            and u.allegiance in defender_allegiances
            and u.is_combat_unit()
        ]
        if remaining_defender_combat_units:
            return False

        for unit in attackers:
            if not unit.is_on_map or not unit.position:
                continue
            if unit.position[0] is None or unit.position[1] is None:
                continue
            if not (unit.is_army() or unit.is_wing()):
                continue
            if unit.allegiance != self.active_player:
                continue
            from_hex = Hex.offset_to_axial(*unit.position)
            if target_hex not in from_hex.neighbors():
                continue
            if self.map.can_stack_move_to([unit], target_hex):
                return True
        return False

    def advance_after_combat(self, attackers, target_hex):
        candidates = []
        for unit in attackers:
            if not unit.is_on_map or not unit.position:
                continue
            if None in unit.position:
                continue
            if not (unit.is_army() or unit.is_wing()):
                continue

            from_hex = Hex.offset_to_axial(*unit.position)
            if target_hex not in from_hex.neighbors():
                continue
            candidates.append(unit)

        if not candidates:
            return []

        remaining_by_source = {}
        no_adjacent_enemy = {}
        for u in candidates:
            src = tuple(u.position)
            remaining_by_source[src] = remaining_by_source.get(src, 0) + 1
            if src not in no_adjacent_enemy:
                src_hex = Hex.offset_to_axial(*src)
                no_adjacent_enemy[src] = not self.map.is_adjacent_to_enemy(src_hex, u)

        moved = []
        groups = [
            [u for u in candidates if u.is_wing()],
            [u for u in candidates if u.unit_type == UnitType.CAVALRY],
            [u for u in candidates if u.is_army() and u.unit_type != UnitType.CAVALRY],
        ]

        for group in groups:
            pool = list(group)
            while pool:
                legal = [
                    u for u in pool
                    if self.map.can_stack_move_to([u], target_hex)
                    and not self._would_leave_leaders_alone_after_advance(u)
                ]
                if not legal:
                    break

                random.shuffle(legal)
                legal.sort(key=lambda u: self._advance_priority_key(u, remaining_by_source, no_adjacent_enemy))
                chosen = legal[0]
                source_before_move = tuple(chosen.position)
                self.game_state.move_unit(chosen, target_hex)
                moved.append(chosen)

                if source_before_move in remaining_by_source and remaining_by_source[source_before_move] > 0:
                    remaining_by_source[source_before_move] -= 1

                pool.remove(chosen)

        return moved

    def _would_leave_leaders_alone_after_advance(self, unit):
        if not unit.position or unit.position[0] is None or unit.position[1] is None:
            return False
        src_hex = Hex.offset_to_axial(*unit.position)
        src_units = [
            u for u in self.map.get_units_in_hex(src_hex.q, src_hex.r)
            if u.is_on_map
            and u.allegiance == unit.allegiance
            and u.transport_host is None
        ]
        has_leader = any(u.is_leader() for u in src_units)
        if not has_leader:
            return False

        escort_count = sum(
            1
            for u in src_units
            if u.is_control_unit()
        )
        return escort_count <= 1

    def _advance_priority_key(self, unit, remaining_by_source, no_adjacent_enemy):
        src = tuple(unit.position)
        source_has_no_adjacent_enemy = no_adjacent_enemy.get(src, False)
        leaves_source_empty = remaining_by_source.get(src, 0) <= 1
        return (
            0 if source_has_no_adjacent_enemy else 1,
            1 if leaves_source_empty else 0,
        )

    def _resolve_leader_escapes(self, leader_origins, leader_stack_has_army):
        checks = [
            LeaderEscapeCheck(
                leader=leader,
                origin_hex=origin_hex,
                allow_fleet_destinations=False,
                roll_required=True,
                require_prior_combat_stack=True,
                prior_had_combat_stack=bool(leader_stack_has_army.get(leader)),
                skip_if_allied_combat_present=True,
                auto_place_on_success=False,
            )
            for leader, origin_hex in leader_origins.items()
        ]
        return self.game_state._get_leader_escape_handler().handle_leader_escapes(checks, auto_resolve_ai=True)

    def _get_nearest_friendly_combat_stacks(self, leader, origin_hex):
        candidates = []
        for (q, r), units in self.map.unit_map.items():
            if not units:
                continue
            if not any(
                u.allegiance == leader.allegiance
                and u.is_on_map
                and u.is_combat_unit()
                for u in units
            ):
                continue
            candidates.append(Hex(q, r))

        if not candidates:
            return []

        min_distance = min(origin_hex.distance_to(h) for h in candidates)
        return [h for h in candidates if origin_hex.distance_to(h) == min_distance]

    @staticmethod
    def _is_leader_only_stack(units):
        live_units = [u for u in units if u.is_on_map]
        if not live_units:
            return False
        return all(u.is_leader() for u in live_units)

    @staticmethod
    def _attack_triggers_leader_stack_escape(attackers):
        return any(u.is_control_unit()
            and u.is_on_map
            for u in attackers
        )

    def _defenders_have_citadel(self, defenders):
        return any(u.is_citadel() and u.is_on_map for u in defenders)

    def _is_ws_ground_combat_unit(self, unit):
        return bool(unit.allegiance == WS and unit.is_on_map and unit.is_army())

    def _is_ws_air_combat_unit(self, unit):
        return bool(unit.allegiance == WS and unit.is_on_map and unit.is_flier())

    def _combat_blocked_by_citadel_rule(self, attackers, defenders):
        if not self._defenders_have_citadel(defenders):
            return False
        has_ws_ground = any(self._is_ws_ground_combat_unit(u) for u in attackers)
        has_ws_air = any(self._is_ws_air_combat_unit(u) for u in attackers)
        return has_ws_ground and not has_ws_air

    def _filter_ws_ground_attackers_vs_citadel(self, attackers, defenders):
        if not self._defenders_have_citadel(defenders):
            return list(attackers)
        return [u for u in attackers if not self._is_ws_ground_combat_unit(u)]

    def clear_leader_tactical_overrides(self):
        for unit in self.units:
            if unit.is_leader():
                if hasattr(unit, "_tactical_rating_override"):
                    unit._tactical_rating_override = None

    def cleanup_destroyed_units(self, units):
        emperor_destroyed = any(
            getattr(unit, "unit_type", None) == UnitType.EMPEROR
            and getattr(unit, "status", None) == UnitState.DESTROYED
            for unit in units
        )

        all_leader_escapes = []
        for unit in units:
            pending = getattr(unit, "_pending_leader_escapes", None)
            if pending:
                all_leader_escapes.extend(pending)
                unit._pending_leader_escapes = None

        if all_leader_escapes:
            escape_handler = LeaderEscapeHandler(self.game_state, roll_d6_fn=lambda: random.randint(1, 6))
            escape_handler.handle_leader_escapes(all_leader_escapes, auto_resolve_ai=True)

        for unit in units:
            if not unit.is_on_map or not unit.position or unit.position[0] is None or unit.position[1] is None:
                self.map.remove_unit_from_spatial_map(unit)
        if emperor_destroyed:
            self._maybe_promote_highlord_to_emperor()
        self.game_state.finalize_board_state_change()


class CombatClickHandler:
    def __init__(self, game_state, view):
        self.game_state = game_state
        self.view = view
        self.attackers = []
        self.leader_escape_queue = []
        self.active_leader_escape = None
        self.escape_hexes = set()
        self.pending_advance = None

    def handle_click(self, target_hex):
        # UI click state machine:
        # 1) building attacker selection
        # 2) validating common targets
        # 3) confirming and executing combat
        # 4) post-combat leader escape / advance prompts
        if self.active_leader_escape:
            self._handle_leader_escape_click(target_hex)
            return

        units_at_hex = self.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
        active_player = self.game_state.active_player

        # Identify what was clicked
        friendly_units = [
            u for u in units_at_hex
            if u.allegiance == active_player
            and not u.attacked_this_turn
            and self._is_unit_on_map(u)
        ]
        enemy_units = [
            u for u in units_at_hex
            if u.allegiance != active_player
            and u.allegiance != 'neutral'
            and self._is_unit_on_map(u)
        ]

        # --- Scenario 2: Clicked Friendly Stack ---
        if friendly_units:
            mode = self._selection_mode(self.attackers)
            if mode == "naval":
                friendly_units = [u for u in friendly_units if u.is_fleet()]
            elif mode == "land":
                friendly_units = [u for u in friendly_units if not u.is_fleet()]
            if not friendly_units:
                return

            if self.attackers:
                new_selection = list(set(self.attackers + friendly_units))
            else:
                new_selection = friendly_units

            # Calculate common targets for this NEW proposed selection
            common_targets = self.calculate_common_targets(new_selection)

            if not common_targets:
                # Case 2b: "Turn possible targets to none" -> Refresh and show ONLY current stack
                self.attackers = friendly_units
                # Recalculate targets for just this stack
                common_targets = self.calculate_common_targets(self.attackers)
            else:
                # Case 2a: Valid combination
                self.attackers = new_selection

            # Update UI
            self.view.units_clicked.emit(self.attackers)
            self.view.highlight_movement_range(common_targets)
            return

        # --- Scenario 3, 4, 5: Clicked Enemy or Empty ---

        # Check if this hex is a Valid Target for the CURRENT selection
        current_targets = self.calculate_common_targets(self.attackers)
        clicked_offset = target_hex.axial_to_offset()

        if clicked_offset in current_targets:
            # --- Scenario 5: Clicked a Possible Target ---
            from PySide6.QtWidgets import QMessageBox

            is_naval = self._selection_mode(self.attackers) == "naval"
            if is_naval:
                prompt_text = f"Start naval combat with {len(self.attackers)} fleet(s)?"
            else:
                odds_str = self.game_state.combat_service.calculate_odds_preview(
                    self.attackers,
                    enemy_units,
                    target_hex,
                )
                prompt_text = f"Attack with {len(self.attackers)} units?\nOdds: {odds_str}"

            reply = QMessageBox.question(
                None,
                "Confirm Attack",
                prompt_text,
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                committed_attackers = list(self.attackers)
                resolution = self.game_state.combat_service.resolve_combat(
                    self.attackers,
                    target_hex,
                    naval_withdraw_decider=self._ask_naval_withdraw if is_naval else None,
                    dragon_duel_withdraw_decider=self._ask_dragon_duel_withdraw if not is_naval else None,
                )
                show_combat_result_popup(
                    self.game_state,
                    title="Combat Details",
                    attackers=self.attackers,
                    defenders=enemy_units,
                    resolution=resolution,
                    context="manual_combat",
                    target_hex=target_hex,
                )
                # Mark attackers
                for u in self.attackers:
                    u.attacked_this_turn = True

                # Clear all
                self.reset_selection()

                if is_naval:
                    self.view.sync_with_model()
                    return

                leader_escape = resolution.get("leader_escape_requests", []) if resolution else []
                advance_available = bool(resolution and resolution.get("advance_available"))
                if advance_available:
                    self.pending_advance = {
                        "attackers": committed_attackers,
                        "target_hex": target_hex,
                    }
                if leader_escape:
                    self._begin_leader_escape(leader_escape)
                else:
                    self._prompt_advance_after_combat()
            return

        # If not a valid target...
        if enemy_units:
            # --- Scenario 3: Clicked Invalid Enemy ---
            self.reset_selection()
        else:
            # --- Scenario 4: Clicked Empty Hex ---
            self.reset_selection()

    def reset_selection(self):
        self.attackers = []
        if not self.active_leader_escape:
            self.view.highlight_movement_range([])
        self.view.units_clicked.emit([])

    def calculate_common_targets(self, attackers):
        """
        Returns list of (col, row) valid targets that ALL attacker stacks can attack.
        Actually, the rule is: "several stacks... can combine... against a defender's hex".
        This means the target hex must be adjacent to ALL participating stacks.
        """
        attackers = [u for u in attackers if self._is_unit_on_map(u)]
        if not attackers:
            return []

        # Group attackers by location (Stack)
        from collections import defaultdict
        stacks = defaultdict(list)
        for u in attackers:
            if u.position and None not in u.position:
                stacks[u.position].append(u)

        if not stacks:
            return []

        # Find valid targets for EACH stack
        stack_targets = []
        for pos, unit_list in stacks.items():
            # Get targets for this specific stack
            # A target is valid if it has enemies and is adjacent (and valid terrain)
            targets_for_this_stack = set(self.calculate_valid_targets(unit_list))
            stack_targets.append(targets_for_this_stack)

        # Find intersection
        if not stack_targets:
            return []

        # Combined attacks require geometric intersection of each stack's legal targets.
        common_set = set.intersection(*stack_targets)
        return list(common_set)

    def calculate_valid_targets(self, attackers):
        """Returns list of (col, row) tuples for valid attack targets."""
        attackers = [u for u in attackers if self._is_unit_on_map(u)]
        if not attackers:
            return []

        if self._selection_mode(attackers) == "naval":
            return self._calculate_naval_targets(attackers)

        # 1. Get all unique positions of attackers (usually they are in one stack, but could be multi-hex attack)
        attacker_hexes = set()
        for u in attackers:
            if u.position and None not in u.position:
                from src.game.map import Hex
                attacker_hexes.add(Hex.offset_to_axial(*u.position))

        valid_target_offsets = set()

        # 2. Check neighbors of all attacker positions
        for start_hex in attacker_hexes:
            for next_hex in start_hex.neighbors():
                enemy_units = [
                    u for u in self.game_state.map.get_units_in_hex(next_hex.q, next_hex.r)
                    if self._is_unit_on_map(u)
                    and u.allegiance not in (self.game_state.active_player, "neutral", None)
                ]
                if not enemy_units:
                    continue

                if not self.game_state.can_units_attack_target_hex(attackers, next_hex):
                    continue
                if not self.game_state.combat_service.can_units_attack_stack(attackers, enemy_units, target_hex=next_hex):
                    continue
                valid_target_offsets.add(next_hex.axial_to_offset())

        return list(valid_target_offsets)

    def _calculate_naval_targets(self, attackers):
        fleets = [u for u in attackers if u.is_fleet()]
        if not fleets:
            return []

        valid_target_offsets = set()
        for (q, r), units in self.game_state.map.unit_map.items():
            enemy_fleets = [
                u for u in units
                if u.is_fleet()
                and u.allegiance != self.game_state.active_player
                and u.allegiance != "neutral"
                and self._is_unit_on_map(u)
            ]
            if not enemy_fleets:
                continue
            from src.game.map import Hex
            target_hex = Hex(q, r)
            if any(self.game_state.combat_service.can_fleet_attack_hex(f, target_hex) for f in fleets):
                valid_target_offsets.add(target_hex.axial_to_offset())

        return list(valid_target_offsets)

    def _is_unit_on_map(self, unit):
        return bool(unit.is_on_map and unit.position and None not in unit.position)

    def _selection_mode(self, attackers):
        if not attackers:
            return None
        fleets = [u for u in attackers if u.is_fleet()]
        if fleets and len(fleets) == len(attackers):
            return "naval"
        return "land"

    def _has_enemy_citadel_target(self, target_hex, attackers):
        active_player = self.game_state.active_player
        enemy_citadel_present = any(
            u.is_citadel()
            and u.allegiance != active_player
            and u.allegiance != "neutral"
            and self._is_unit_on_map(u)
            for u in self.game_state.map.get_units_in_hex(target_hex.q, target_hex.r)
        )
        if not enemy_citadel_present:
            return False

        if active_player == WS:
            has_air = any(u.is_flier() for u in attackers)
            return has_air
        return True

    def _ask_naval_withdraw(self, side_allegiance, round_number):
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            None,
            "Naval Withdrawal",
            f"Round {round_number}: should {side_allegiance} withdraw all fleets and end naval combat?",
            QMessageBox.Yes | QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _ask_dragon_duel_withdraw(self, side_allegiance, round_number):
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            None,
            "Dragon Duel",
            f"Dragon duel round {round_number}: should {side_allegiance} withdraw dragons?",
            QMessageBox.Yes | QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _begin_leader_escape(self, leader_escape_requests):
        self.leader_escape_queue = list(leader_escape_requests)
        self._activate_next_leader_escape()

    def _activate_next_leader_escape(self):
        if not self.leader_escape_queue:
            self.active_leader_escape = None
            self.escape_hexes = set()
            self.view.highlight_movement_range([])
            self._prompt_advance_after_combat()
            return

        self.active_leader_escape = self.leader_escape_queue.pop(0)
        leader = getattr(self.active_leader_escape, "leader", None)
        options = list(getattr(self.active_leader_escape, "options", []) or [])
        player = self.game_state.get_player(getattr(leader, "allegiance", None)) if leader else None
        if leader and options and player and player.is_ai:
            # AI escapes resolve immediately; humans get a highlighted choice set.
            destination = self.game_state._get_leader_escape_handler().choose_escape_destination(leader, options)
            if destination:
                self.game_state.move_unit(leader, destination)
                print(f"Leader {caption_id(leader.id)} escaped to {destination.axial_to_offset()} (AI).")
            self.active_leader_escape = None
            self.escape_hexes = set()
            self.view.sync_with_model()
            self._activate_next_leader_escape()
            return

        self.escape_hexes = {h.axial_to_offset() for h in self.active_leader_escape.options}
        self.view.highlight_movement_range(list(self.escape_hexes))
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            None,
            "Leader Escape",
            f"Select a friendly stack for {self.active_leader_escape.leader.id} to escape."
        )

    def _handle_leader_escape_click(self, target_hex):
        clicked_offset = target_hex.axial_to_offset()
        if clicked_offset not in self.escape_hexes:
            return

        leader = self.active_leader_escape.leader
        self.game_state.move_unit(leader, target_hex)
        leader._tactical_rating_override = 0
        print(f"Leader {caption_id(leader.id)} escaped to {clicked_offset}.")

        self.active_leader_escape = None
        self.escape_hexes = set()
        self.view.sync_with_model()
        self._activate_next_leader_escape()

    def _prompt_advance_after_combat(self):
        if not self.pending_advance:
            return

        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            None,
            "Advance?",
            "Advance?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            moved_units = self.game_state.combat_service.advance_after_combat(
                self.pending_advance["attackers"],
                self.pending_advance["target_hex"],
            )
            if moved_units:
                print(f"Advance after combat: moved {len(moved_units)} units.")

        self.pending_advance = None
        self.view.sync_with_model()
