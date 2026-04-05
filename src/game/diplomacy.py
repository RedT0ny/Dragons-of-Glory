import random
from dataclasses import dataclass
from typing import List, Optional

from src.content.constants import HL, WS
from src.content.specs import LocType, UnitState, UnitType
from src.game.map import Hex


@dataclass(frozen=True)
class ActivationAttempt:
    country_id: str
    active_side: str
    ws_rating: int
    hl_rating: int
    solamnic_bonus: int
    country_activation_bonus: int
    event_activation_bonus: int
    target_rating: int


@dataclass(frozen=True)
class ActivationRollResult:
    roll: int
    effective_roll: int
    bonus_applied: int
    success: bool


@dataclass(frozen=True)
class DeploymentPlan:
    country_filter: Optional[str]
    message_title: str
    message_text: str


@dataclass(frozen=True)
class InvasionOutcome:
    success: bool
    title: str
    message: str
    winner: Optional[str] = None


class DiplomacyService:
    """Domain logic for diplomacy activation checks and roll resolution."""

    def __init__(self, game_state):
        self.game_state = game_state

    def is_country_neutral(self, country_id: str) -> bool:
        country = self.game_state.countries.get(country_id)
        return bool(country and country.allegiance == "neutral")

    def build_activation_attempt(self, country_id: str) -> ActivationAttempt | None:
        country = self.game_state.countries.get(country_id)
        if not country:
            return None

        active_side = self.game_state.active_player
        ws_rating, hl_rating = country.alignment

        solamnic_bonus = 0
        if active_side == WS and self.game_state.is_solamnic_country_for_tower_rule(country.id):
            solamnic_bonus = self.game_state.get_ws_solamnic_activation_bonus()
        country_activation_bonus = 0
        if hasattr(self.game_state, "get_country_activation_bonus"):
            country_activation_bonus = int(self.game_state.get_country_activation_bonus(active_side, country.id) or 0)
        event_bonus = 0
        if hasattr(self.game_state, "get_activation_bonus"):
            event_bonus = self.game_state.get_activation_bonus(active_side)

        target_rating = ws_rating + solamnic_bonus if active_side == WS else hl_rating
        target_rating += country_activation_bonus
        return ActivationAttempt(
            country_id=country.id,
            active_side=active_side,
            ws_rating=ws_rating,
            hl_rating=hl_rating,
            solamnic_bonus=solamnic_bonus,
            country_activation_bonus=country_activation_bonus,
            event_activation_bonus=event_bonus,
            target_rating=target_rating,
        )

    def roll_activation(self, target_rating: int, roll_bonus: int = 0) -> ActivationRollResult:
        roll = random.randint(1, 10)
        effective_roll = max(1, roll - int(roll_bonus or 0))
        return ActivationRollResult(
            roll=roll,
            effective_roll=effective_roll,
            bonus_applied=int(roll_bonus or 0),
            success=effective_roll <= target_rating,
        )

    def activate_country(self, country_id: str, allegiance: str) -> bool:
        country = self.game_state.countries.get(country_id)
        if not country:
            return False
        self.game_state.activate_country(country_id, allegiance)
        return True

    def build_deployment_plan(self, effects: dict, active_player: str) -> DeploymentPlan:
        country_filter = effects.get("alliance")
        alliance_already_activated = bool(effects.get("alliance_already_activated"))
        if "alliance" in effects and not alliance_already_activated:
            self.game_state.activate_country(country_filter, active_player)

        if "add_units" in effects:
            country_filter = None

        message_title = "Deployment"
        message_text = "Reinforcements have arrived!\n\nDeploy your new forces."
        if "alliance" in effects and "add_units" not in effects:
            message_text = (
                f"{effects['alliance'].title()} has joined the war!\n\n"
                "Deploy forces in their territory."
            )

        return DeploymentPlan(
            country_filter=country_filter,
            message_title=message_title,
            message_text=message_text,
        )

    def resolve_invasion(self, country_id: str, invasion_data: dict) -> InvasionOutcome:
        country = self.game_state.countries.get(country_id)
        if not country:
            return InvasionOutcome(
                success=False,
                title="Invasion",
                message="Country not found.",
            )

        if invasion_data.get("strength", 0) <= 0:
            reason = invasion_data.get("reason") or "No eligible invasion force."
            return InvasionOutcome(
                success=False,
                title="Invasion",
                message=reason,
            )

        invader_sp = invasion_data["strength"]
        defender_sp = country.strength
        modifier = self._invasion_modifier(invader_sp, defender_sp)

        base_ws = country.alignment[0] + 2
        base_hl = country.alignment[1] + modifier

        rounds: List[str] = []
        round_bonus = 0
        winner = None

        for _ in range(20):
            ws_target = base_ws + round_bonus
            ws_roll = random.randint(1, 10)
            rounds.append(f"WS roll {ws_roll} vs {ws_target}")
            if ws_roll <= ws_target:
                winner = WS
                break

            hl_target = base_hl + round_bonus
            hl_roll = random.randint(1, 10)
            rounds.append(f"HL roll {hl_roll} vs {hl_target}")
            if hl_roll <= hl_target:
                winner = HL
                break

            round_bonus += 1

        if not winner:
            return InvasionOutcome(
                success=False,
                title="Invasion",
                message="Invasion could not be resolved.",
            )

        self.game_state.activate_country(country_id, winner)

        summary_lines = [
            f"Invader SP: {invader_sp} | Defender SP: {defender_sp}",
            f"Modifier: {modifier}",
            "Rolls:",
            *rounds,
            f"{country_id.capitalize()} joins {winner.title()}",
        ]
        message = "\n".join(summary_lines)
        title = f"Invasion!"

        return InvasionOutcome(
            success=True,
            title=title,
            message=message,
            winner=winner,
        )

    def _invasion_modifier(self, invader_sp: int, defender_sp: int) -> int:
        if defender_sp <= 0: return 6
        ratio: float = invader_sp / defender_sp
        if ratio < 0.2: return -6
        if ratio < 0.25: return -5
        if ratio < 0.33: return -4
        if ratio < 0.5: return -3
        if ratio < 0.66: return -2
        if ratio < 1: return -1
        if ratio < 1.5: return 0
        if ratio < 2.0: return 1
        if ratio < 3.0: return 2
        if ratio < 4.0: return 3
        if ratio < 5.0: return 4
        if ratio < 6.0: return 5
        return 6


class ConquestService:
    """Rule 9 conquest/libration domain logic."""

    def __init__(self, game_state):
        self.game_state = game_state

    def _update_location_occupiers(self):
        gs = self.game_state
        for map_loc in gs.map.locations.values():
            if not map_loc or not map_loc.coords:
                continue
            hex_obj = Hex.offset_to_axial(*map_loc.coords)
            for unit in gs.map.get_units_in_hex(hex_obj.q, hex_obj.r):
                if (
                    unit.is_on_map
                    and unit.allegiance != map_loc.occupier
                    and (unit.is_army() or (unit.is_wing() and map_loc.loc_type != LocType.UNDERCITY.value))
                ):
                    map_loc.occupier = unit.allegiance
                    break

    def _is_country_fully_occupied_by_enemy(self, country) -> bool:
        gs = self.game_state
        enemy = gs.get_enemy_allegiance(country.allegiance)
        if not enemy:
            return False
        if not country.locations:
            return False
        return all(loc.occupier == enemy for loc in country.locations.values())

    def _destroy_country_upon_conquest(self, country, conqueror: str):
        gs = self.game_state
        destroyed_count = 0
        for unit in gs.units:
            if unit.land != country.id:
                continue

            if unit.is_fleet():
                if unit.status not in UnitState.on_map_states() and unit.status != UnitState.DESTROYED:
                    unit.destroy()
                    gs.map.remove_unit_from_spatial_map(unit)
                    destroyed_count += 1
                continue

            is_army = hasattr(unit, "is_army") and unit.is_army()
            is_wing = hasattr(unit, "is_wing") and unit.is_wing()
            is_leader = hasattr(unit, "is_leader") and unit.is_leader()
            if not (is_army or is_wing or is_leader):
                continue
            if unit.status == UnitState.DESTROYED:
                continue

            unit.destroy()
            gs.map.remove_unit_from_spatial_map(unit)
            destroyed_count += 1

        country.allegiance = conqueror
        country.conquered = True
        print(f"Country {country.id} conquered. Destroyed units: {destroyed_count}")

    def _apply_country_conquest_or_liberation(self, country, conqueror: str):
        if country.conquered:
            country.allegiance = conqueror
            country.conquered = False
            print(f"Country {country.id} liberated for {conqueror}.")
            return
        self._destroy_country_upon_conquest(country, conqueror)

    def _enforce_conquered_fleet_replacement_rule(self):
        gs = self.game_state
        any_knight_unconquered = any(
            (not c.conquered) for c in gs._countries_with_tag(gs.tag_knight_countries)
        )

        for unit in gs.units:
            if unit.unit_type != UnitType.FLEET or unit.status != UnitState.RESERVE:
                continue
            country = gs.countries.get(unit.land)
            if not country or not country.conquered:
                continue

            is_knight_country = gs._country_has_tag(country, gs.tag_knight_countries)
            if is_knight_country and any_knight_unconquered:
                continue

            unit.destroy()
            gs.map.remove_unit_from_spatial_map(unit)

    def _apply_standard_country_conquests(self):
        gs = self.game_state
        for country in gs.countries.values():
            if country.allegiance not in (HL, WS):
                continue
            if gs._country_has_tag(country, gs.tag_knight_countries) and country.allegiance == WS:
                continue
            if self._is_country_fully_occupied_by_enemy(country):
                conqueror = gs.get_enemy_allegiance(country.allegiance)
                if conqueror:
                    self._apply_country_conquest_or_liberation(country, conqueror)

    def _apply_solamnic_group_conquest(self):
        gs = self.game_state
        group = [c for c in gs._countries_with_tag(gs.tag_knight_countries) if c.allegiance == WS]
        if not group:
            return
        fully_occupied = all(self._is_country_fully_occupied_by_enemy(c) for c in group)
        if not fully_occupied:
            return
        for country in group:
            conqueror = gs.get_enemy_allegiance(country.allegiance)
            if conqueror:
                self._apply_country_conquest_or_liberation(country, conqueror)

    def resolve_end_of_combat_conquest(self):
        gs = self.game_state
        if not gs.map:
            return
        self._update_location_occupiers()
        self._apply_standard_country_conquests()
        self._apply_solamnic_group_conquest()
        self._enforce_conquered_fleet_replacement_rule()
        gs.update_territory_overrides()
        gs.invalidate_overlays({"control", "territory", "supply"})
