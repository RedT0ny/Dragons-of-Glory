import random
from dataclasses import dataclass
from typing import List
from src.content.config import CRT_DATA
from src.content.specs import HexsideType, LocType, TerrainType, UnitRace, UnitState, UnitType
from src.content.constants import MIN_COMBAT_ROLL, MAX_COMBAT_ROLL
from src.content.loader import load_data
@dataclass
class LeaderEscapeRequest:
    leader: object
    options: List[object]


def apply_dragon_orb_precombat(attackers, defenders, consume_asset_fn, roll_d6_fn=None):
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
        if not any(_is_dragon_or_draconian(unit) for unit in opposing):
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
                leader.destroy()
                consume_asset_fn(orb, leader)
                logs.append(
                    f"Dragon Orb ({side_name}) failed: {leader.id} rolled {roll} > TR {tactical_rating}; leader and orb destroyed."
                )
                continue

            destroyed_dragons = []
            for enemy in opposing:
                if not (enemy.is_on_map and _is_dragon(enemy)):
                    continue
                enemy.destroy()
                destroyed_dragons.append(enemy)
            consume_asset_fn(orb, leader)
            logs.append(
                f"Dragon Orb ({side_name}) succeeded: {leader.id} rolled {roll} <= TR {tactical_rating}; destroyed {len(destroyed_dragons)} dragon unit(s)."
            )

    return logs


def _get_equipped_asset(unit, asset_id: str):
    for asset in getattr(unit, "equipment", []) or []:
        if getattr(asset, "id", None) == asset_id:
            return asset
    return None


def _is_dragon(unit) -> bool:
    race = getattr(unit, "race", None)
    if race == UnitRace.DRAGON:
        return True
    if isinstance(race, str):
        return race.lower() == UnitRace.DRAGON.value
    return False


def _is_draconian(unit) -> bool:
    race = getattr(unit, "race", None)
    if race == UnitRace.DRACONIAN:
        return True
    if isinstance(race, str):
        return race.lower() == UnitRace.DRACONIAN.value
    return False


def _is_dragon_or_draconian(unit) -> bool:
    return _is_dragon(unit) or _is_draconian(unit)

class CombatResolver:
    """
    Handles resolution of Land and Air combat according to Rule 7 (DL_11).
    """
    def __init__(self, attackers, defenders, terrain_type, game_state=None):
        self.attackers = attackers
        self.defenders = defenders
        self.terrain_type = terrain_type
        self.game_state = game_state
        # Use the centralized loader
        self.crt_data = load_data(CRT_DATA) # csv or yaml?

    def calculate_odds(self, attacker_cs, defender_cs):
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

    def resolve(self):
        # 1. Calculate Odds
        attacker_cs = sum(u.combat_rating for u in self.attackers)
        defender_cs = sum(u.combat_rating for u in self.defenders)
        defender_cs *= self._get_defender_combat_multiplier()
        
        odds_str = self.calculate_odds(attacker_cs, defender_cs)
        
        # 2. Determine DRMs (Leader Tactical Ratings, Terrain, etc.)
        drm = self.calculate_total_drm()

        # 3. Roll 1d10
        roll = random.randint(1, 10)

        # min -5, max 16
        final_roll = max(MIN_COMBAT_ROLL, min(MAX_COMBAT_ROLL, roll + drm))

        # 4. Look up result from CRT data
        result = self.crt_data[final_roll][odds_str]

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
                unit.eliminate()
        elif apply_deplete_all:
            for unit in affected:
                if unit.status.name == "DEPLETED":
                    unit.eliminate()
                elif unit.status.name == "ACTIVE":
                    unit.deplete()

        if depletion_steps:
            self._apply_depletion_steps(affected, depletion_steps)

        if must_retreat and not (not is_attacker and self._defender_ignores_retreat()):
            self._apply_retreats(affected)

        if not (apply_eliminate_all or apply_deplete_all or depletion_steps or must_retreat):
            error_msg = f"Invalid combat result: {result_code}"
            raise ValueError(error_msg)

    def calculate_total_drm(self):
        drm = 0
        defender_hex = self._get_defender_hex()
        defender_terrain = self.terrain_type
        defender_location = self._get_defender_location()
        defender_loc_type = self._normalize_loc_type(defender_location)

        # LEADERS
        atk_leader = max(
            [u.tactical_rating for u in self.attackers if hasattr(u, "is_leader") and u.is_leader()],
            default=0,
        )
        def_leader = max(
            [u.tactical_rating for u in self.defenders if hasattr(u, "is_leader") and u.is_leader()],
            default=0,
        )
        drm += atk_leader
        drm -= def_leader

        # DRAGONS (Dragon wings only)
        drm += sum(
            u.combat_rating
            for u in self.attackers
            if u.unit_type == UnitType.WING and self._is_dragon_race(u)
        )
        drm -= sum(
            u.combat_rating
            for u in self.defenders
            if u.unit_type == UnitType.WING and self._is_dragon_race(u)
        )

        # CAVALRY (+1 attacker only, not vs location/forest/jungle)
        cavalry_blocked = bool(defender_location) or defender_terrain in (TerrainType.FOREST, TerrainType.JUNGLE)
        if not cavalry_blocked and any(u.unit_type == UnitType.CAVALRY for u in self.attackers):
            drm += 1

        # FLIGHT (+1 attacker if has fliers, -1 defender if has fliers)
        flight_blocked = (
            defender_loc_type == LocType.UNDERCITY.value
            or defender_terrain in (TerrainType.FOREST, TerrainType.MOUNTAIN, TerrainType.JUNGLE)
        )
        if not flight_blocked:
            if any(self._is_flier(u) for u in self.attackers):
                drm += 1
            if any(self._is_flier(u) for u in self.defenders):
                drm -= 1

        # LOCATIONS (defender benefit only)
        if defender_loc_type == LocType.FORTRESS.value:
            drm -= 4
        elif defender_loc_type in (LocType.CITY.value, LocType.PORT.value):
            drm -= 2
        elif defender_loc_type == LocType.UNDERCITY.value:
            drm -= 10

        # CROSSINGS (if any attacking army crosses these)
        crossings = self._get_attacker_crossing_types(defender_hex)
        if "river" in crossings:
            drm -= 4
        if "bridge" in crossings:
            drm -= 4
        if "ford" in crossings:
            drm -= 3
        if "pass" in crossings:
            drm -= 2

        # TERRAIN AFFINITY
        drm += self._count_attacker_terrain_affinity_bonus()
        drm -= self._count_defender_terrain_affinity_bonus(defender_hex)

        # EVENT COMBAT BONUS (active player, current battle turn only)
        if self.game_state and hasattr(self.game_state, "get_combat_bonus"):
            active_player = getattr(self.game_state, "active_player", None)
            if active_player and any(getattr(u, "allegiance", None) == active_player for u in self.attackers):
                drm += int(self.game_state.get_combat_bonus(active_player))

        return drm

    def _is_dragon_race(self, unit):
        race = getattr(unit, "race", None)
        if race == UnitRace.DRAGON:
            return True
        if isinstance(race, str) and race.lower() == UnitRace.DRAGON.value:
            return True
        return False

    def _is_flier(self, unit):
        return unit.unit_type in (UnitType.WING, UnitType.CITADEL)

    def _get_defender_hex(self):
        if not self.game_state or not self.game_state.map:
            return None
        for unit in self.defenders:
            if not getattr(unit, "position", None):
                continue
            col, row = unit.position
            if col is None or row is None:
                continue
            from src.game.map import Hex
            return Hex.offset_to_axial(col, row)
        return None

    def _get_defender_location(self):
        defender_hex = self._get_defender_hex()
        if not defender_hex or not self.game_state or not self.game_state.map:
            return None
        return self.game_state.map.get_location(defender_hex)

    def _get_defender_combat_multiplier(self):
        loc = self._get_defender_location()
        loc_type = self._normalize_loc_type(loc)
        if loc_type == LocType.FORTRESS.value:
            return 3
        if loc_type in (LocType.CITY.value, LocType.PORT.value):
            return 2
        return 1

    def _defender_ignores_retreat(self):
        return bool(self._get_defender_location())

    def _get_attacker_crossing_types(self, defender_hex):
        crossings = set()
        if not defender_hex or not self.game_state or not self.game_state.map:
            return crossings
        for unit in self.attackers:
            if not (hasattr(unit, "is_army") and unit.is_army()):
                continue
            if not getattr(unit, "position", None):
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
                crossings.add("bridge")
                continue

            hexside = self.game_state.map.get_effective_hexside(attacker_hex, defender_hex)
            if hexside in (
                HexsideType.RIVER,
                HexsideType.RIVER.value,
                HexsideType.DEEP_RIVER,
                HexsideType.DEEP_RIVER.value,
            ):
                crossings.add("river")
            elif hexside in (HexsideType.BRIDGE, HexsideType.BRIDGE.value):
                crossings.add("bridge")
            elif hexside in (HexsideType.FORD, HexsideType.FORD.value):
                crossings.add("ford")
            elif hexside in (HexsideType.PASS, HexsideType.PASS.value):
                crossings.add("pass")
        return crossings

    def _normalize_loc_type(self, loc):
        if not isinstance(loc, dict):
            return None
        value = loc.get("type")
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
            if not (hasattr(unit, "is_army") and unit.is_army()):
                continue
            if getattr(unit, "terrain_affinity", None) == terrain:
                bonus += 1
        return bonus

    def _get_affected_armies(self, units):
        affected = []
        for unit in units:
            if hasattr(unit, "is_leader") and unit.is_leader():
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if unit.unit_type == UnitType.WING or (hasattr(unit, "is_army") and unit.is_army()):
                affected.append(unit)
        return affected

    def _apply_depletion_steps(self, units, steps):
        for _ in range(steps):
            ground_active = [u for u in units if u.status.name == "ACTIVE" and u.unit_type != UnitType.WING]
            if ground_active:
                target = min(ground_active, key=lambda u: u.combat_rating)
                target.deplete()
                continue

            ground_depleted = [u for u in units if u.status.name == "DEPLETED" and u.unit_type != UnitType.WING]
            if ground_depleted:
                target = min(ground_depleted, key=lambda u: u.combat_rating)
                target.eliminate()
                continue

            wing_active = [u for u in units if u.status.name == "ACTIVE" and u.unit_type == UnitType.WING]
            if wing_active:
                target = min(wing_active, key=lambda u: u.combat_rating)
                target.deplete()
                continue

            wing_depleted = [u for u in units if u.status.name == "DEPLETED" and u.unit_type == UnitType.WING]
            if wing_depleted:
                target = min(wing_depleted, key=lambda u: u.combat_rating)
                target.eliminate()
                continue

            break

    def _apply_retreats(self, units):
        if not self.game_state or not self.game_state.map:
            return

        from src.game.map import Hex

        for unit in units:
            if not unit.position or unit.position[0] is None or unit.position[1] is None:
                continue
            start_hex = Hex.offset_to_axial(*unit.position)
            valid_hexes = self._get_valid_retreat_hexes(unit, start_hex)
            if not valid_hexes:
                unit.eliminate()
                continue
            retreat_hex = random.choice(valid_hexes)
            self.game_state.move_unit(unit, retreat_hex)

    def _get_valid_retreat_hexes(self, unit, start_hex):
        valid = []
        for neighbor in start_hex.neighbors():
            col, row = neighbor.axial_to_offset()
            if not self.game_state.is_hex_in_bounds(col, row):
                continue
            if not self.game_state.map.can_unit_land_on_hex(unit, neighbor):
                continue
            if self.game_state.map.has_enemy_army(neighbor, unit.allegiance):
                continue
            if not self.game_state.map.can_stack_move_to([unit], neighbor):
                continue
            cost = self.game_state.map.get_movement_cost(unit, start_hex, neighbor)
            if cost == float('inf') or cost is None:
                continue

            friendly_present = any(
                u.allegiance == unit.allegiance and (u.is_army() or u.unit_type == UnitType.WING)
                for u in self.game_state.map.get_units_in_hex(neighbor.q, neighbor.r)
            )
            if not friendly_present and self.game_state.map.is_adjacent_to_enemy(neighbor, unit):
                continue

            valid.append(neighbor)
        return valid


class NavalCombatResolver:
    """
    Resolves Rule 8 fleet-to-fleet combat.
    """
    def __init__(self, game_state, attackers, defenders, roll_d10_fn=None, roll_d6_fn=None):
        self.game_state = game_state
        self.attackers = [u for u in attackers if getattr(u, "unit_type", None) == UnitType.FLEET and getattr(u, "is_on_map", False)]
        self.defenders = [u for u in defenders if getattr(u, "unit_type", None) == UnitType.FLEET and getattr(u, "is_on_map", False)]
        self._roll_d10 = roll_d10_fn or (lambda: random.randint(1, 10))
        self._roll_d6 = roll_d6_fn or (lambda: random.randint(1, 6))

    def resolve(self, withdraw_decider=None):
        rounds = 0
        while self.attackers and self.defenders:
            rounds += 1
            atk_round = [u for u in self.attackers if getattr(u, "is_on_map", False)]
            def_round = [u for u in self.defenders if getattr(u, "is_on_map", False)]
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
                    if not getattr(target, "is_on_map", False):
                        break
                    self._apply_hit_to_fleet(target)

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
            "attacker_survivors": len([u for u in self.attackers if getattr(u, "is_on_map", False)]),
            "defender_survivors": len([u for u in self.defenders if getattr(u, "is_on_map", False)]),
        }

    def _roll_hits(self, fleet):
        threshold = self._fleet_attack_rating(fleet)
        roll = self._roll_d10()
        return roll <= threshold

    def _fleet_attack_rating(self, fleet):
        base = getattr(fleet, "combat_rating", 0)
        passengers = list(getattr(fleet, "passengers", []) or [])
        leader_bonus = 0
        for p in passengers:
            if not (hasattr(p, "is_leader") and p.is_leader()):
                continue
            if p.unit_type not in (UnitType.WIZARD, UnitType.ADMIRAL):
                continue
            leader_bonus = max(leader_bonus, getattr(p, "tactical_rating", 0))
        return base + leader_bonus

    def _select_target(self, attacker, candidates):
        live = [u for u in candidates if getattr(u, "is_on_map", False)]
        if not live:
            return None
        live.sort(key=lambda u: (0 if u.status.name == "DEPLETED" else 1, getattr(u, "combat_rating", 0)))
        return live[0]

    def _apply_hit_to_fleet(self, fleet):
        if fleet.status.name == "ACTIVE":
            fleet.deplete()
            return
        if fleet.status.name == "DEPLETED":
            self._sink_fleet(fleet)

    def _sink_fleet(self, fleet):
        if not getattr(fleet, "position", None) or fleet.position[0] is None or fleet.position[1] is None:
            fleet.eliminate()
            return

        origin_hex = None
        from src.game.map import Hex
        origin_hex = Hex.offset_to_axial(*fleet.position)

        passengers = list(getattr(fleet, "passengers", []) or [])
        fleet.eliminate()
        fleet.river_hexside = None
        if hasattr(fleet, "passengers"):
            fleet.passengers = []
        self.game_state.map.remove_unit_from_spatial_map(fleet)

        for passenger in passengers:
            passenger.transport_host = None
            passenger.is_transported = False
            passenger.position = (None, None)

            if hasattr(passenger, "is_leader") and passenger.is_leader():
                self._resolve_sunk_leader(passenger, origin_hex)
                continue

            if hasattr(passenger, "eliminate"):
                passenger.eliminate()
                self.game_state.map.remove_unit_from_spatial_map(passenger)

    def _resolve_sunk_leader(self, leader, origin_hex):
        if leader.unit_type == UnitType.WIZARD:
            if self._place_leader_with_nearest_friendly(leader, origin_hex, allow_fleet=True):
                return
            leader.destroy()
            return

        roll = self._roll_d6()
        if roll <= 3:
            leader.destroy()
            return
        if self._place_leader_with_nearest_friendly(leader, origin_hex, allow_fleet=False):
            return
        leader.destroy()

    def _place_leader_with_nearest_friendly(self, leader, origin_hex, allow_fleet):
        candidates = []
        for (q, r), units in self.game_state.map.unit_map.items():
            for unit in units:
                if unit.allegiance != leader.allegiance:
                    continue
                if not getattr(unit, "is_on_map", False):
                    continue
                if allow_fleet and unit.unit_type == UnitType.FLEET:
                    candidates.append((q, r))
                    break
                if hasattr(unit, "is_army") and unit.is_army():
                    candidates.append((q, r))
                    break

        if not candidates:
            return False

        from src.game.map import Hex
        hexes = [Hex(q, r) for q, r in candidates]
        target = min(hexes, key=lambda h: origin_hex.distance_to(h))
        if leader.status not in UnitState.on_map_states():
            leader.status = UnitState.ACTIVE
        leader.position = target.axial_to_offset()
        self.game_state.map.add_unit_to_spatial_map(leader)
        return True

    def _withdraw_all(self, side_fleets):
        for fleet in list(side_fleets):
            if not getattr(fleet, "is_on_map", False) or not getattr(fleet, "position", None):
                continue
            if fleet.position[0] is None or fleet.position[1] is None:
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
        self.attackers = [u for u in self.attackers if getattr(u, "is_on_map", False)]
        self.defenders = [u for u in self.defenders if getattr(u, "is_on_map", False)]

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
                friendly_units = [u for u in friendly_units if u.unit_type == UnitType.FLEET]
            elif mode == "land":
                friendly_units = [u for u in friendly_units if u.unit_type != UnitType.FLEET]
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
                odds_str = self.calculate_odds_preview(self.attackers, enemy_units, target_hex)
                prompt_text = f"Attack with {len(self.attackers)} units?\nOdds: {odds_str}"

            reply = QMessageBox.question(
                None,
                "Confirm Attack",
                prompt_text,
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                committed_attackers = list(self.attackers)
                resolution = self.game_state.resolve_combat(
                    self.attackers,
                    target_hex,
                    naval_withdraw_decider=self._ask_naval_withdraw if is_naval else None,
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
            if u.position and u.position[0] is not None and u.position[1] is not None:
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
            if u.position and u.position[0] is not None and u.position[1] is not None:
                from src.game.map import Hex
                attacker_hexes.add(Hex.offset_to_axial(*u.position))

        valid_target_offsets = set()

        # 2. Check neighbors of all attacker positions
        for start_hex in attacker_hexes:
            for next_hex in start_hex.neighbors():
                # Is there an enemy there?
                if self.game_state.map.has_enemy_army(next_hex, self.game_state.active_player):
                    # Validate "Move into" rule
                    if self.is_valid_attack_hex(attackers, start_hex, next_hex):
                        valid_target_offsets.add(next_hex.axial_to_offset())

        return list(valid_target_offsets)

    def _calculate_naval_targets(self, attackers):
        fleets = [u for u in attackers if u.unit_type == UnitType.FLEET]
        if not fleets:
            return []

        valid_target_offsets = set()
        for (q, r), units in self.game_state.map.unit_map.items():
            enemy_fleets = [
                u for u in units
                if u.unit_type == UnitType.FLEET
                and u.allegiance != self.game_state.active_player
                and u.allegiance != "neutral"
                and self._is_unit_on_map(u)
            ]
            if not enemy_fleets:
                continue
            from src.game.map import Hex
            target_hex = Hex(q, r)
            if any(self.game_state.can_fleet_attack_hex(f, target_hex) for f in fleets):
                valid_target_offsets.add(target_hex.axial_to_offset())

        return list(valid_target_offsets)

    def is_valid_attack_hex(self, attackers, start_hex, target_hex):
        """
        Checks if specific units can attack across this hexside.
        """
        hexside = self.game_state.map.get_effective_hexside(start_hex, target_hex)

        if hexside in (HexsideType.MOUNTAIN, HexsideType.MOUNTAIN.value):
            # Check if ALL attackers are capable
            for u in attackers:
                can_cross = u.unit_type == 'wing' or u.unit_type in ['dwarves', 'ogres']
                if not can_cross:
                    return False
        return True

    def calculate_odds_preview(self, attackers, defenders, hex_position):
        """Helper to just get the string "3:1" etc without rolling."""
        # We create a dummy resolver just to calc odds
        terrain = self.game_state.map.get_terrain(hex_position)
        resolver = CombatResolver(attackers, defenders, terrain, game_state=self.game_state)

        attacker_cs = sum(u.combat_rating for u in attackers)
        defender_cs = sum(u.combat_rating for u in defenders)
        defender_cs *= resolver._get_defender_combat_multiplier()
        return resolver.calculate_odds(attacker_cs, defender_cs)

    def _is_unit_on_map(self, unit):
        return bool(getattr(unit, "is_on_map", False) and unit.position and unit.position[0] is not None and unit.position[1] is not None)

    def _selection_mode(self, attackers):
        if not attackers:
            return None
        fleets = [u for u in attackers if u.unit_type == UnitType.FLEET]
        if fleets and len(fleets) == len(attackers):
            return "naval"
        return "land"

    def _ask_naval_withdraw(self, side_allegiance, round_number):
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            None,
            "Naval Withdrawal",
            f"Round {round_number}: should {side_allegiance} withdraw all fleets and end naval combat?",
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
        print(f"Leader {leader.id} escaped to {clicked_offset}.")

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
            moved_units = self.game_state.advance_after_combat(
                self.pending_advance["attackers"],
                self.pending_advance["target_hex"],
            )
            if moved_units:
                print(f"Advance after combat: moved {len(moved_units)} units.")

        self.pending_advance = None
        self.view.sync_with_model()
