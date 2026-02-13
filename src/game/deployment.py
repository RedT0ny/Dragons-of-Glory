from dataclasses import dataclass
from typing import List, Set, Tuple

from src.content.constants import WS, HL
from src.content.specs import GamePhase, UnitType, LocType, UnitState
from src.game.map import Hex


@dataclass(frozen=True)
class UnitDeploymentResult:
    success: bool
    error: str | None = None


class DeploymentService:
    def __init__(self, game_state):
        self.game_state = game_state

    def is_valid_fleet_deployment(self, hex_obj: Hex, country) -> bool:
        """
        Deployment: Any coastal hex or port.
        Replacements: Only ports.
        """
        hex_coords = hex_obj.axial_to_offset()

        # 1. Must be in country
        if not country.is_hex_in_country(*hex_coords):
            return False

        # 2. Check Phase logic
        if self.game_state.phase == GamePhase.REPLACEMENTS:
            # Check if hex has a port
            for loc in country.locations.values():
                if loc.coords == hex_coords and loc.loc_type == "port":
                    return True
            return False

        # Deployment: ports and coastal hexes
        if self.game_state.map.is_coastal(hex_obj):
            return True
        for loc in country.locations.values():
            if loc.coords == hex_coords and loc.loc_type == "port":
                return True
        return False

    def get_deployment_hexes(self, allegiance: str) -> Set[tuple]:
        """
        Returns a set of (x, y) coordinates where a player can deploy.
        Delegates to the Player object.
        """
        if allegiance not in self.game_state.players:
            return set()

        return self.game_state.players[allegiance].get_deployment_hexes(
            self.game_state.countries,
            self.game_state.is_hex_in_bounds
        )

    def get_valid_deployment_hexes(self, unit, allow_territory_wide: bool = False) -> List[Tuple[int, int]]:
        """
        Calculates valid deployment coordinates for a specific unit,
        applying Phase rules, Unit Type restrictions (Fleets), and Terrain checks.
        """
        candidates = []
        player = self.game_state.get_player(unit.allegiance)
        country_deployment = bool(player and player.spec.country_deployment)

        # 1. Gather Candidates based on Phase
        if self.game_state.phase == GamePhase.DEPLOYMENT:
            if country_deployment:
                country = self.game_state.countries.get(unit.land)
                if country:
                    candidates = list(country.territories)
                else:
                    candidates = list(self.get_deployment_hexes(unit.allegiance))
            else:
                # Scenario specific areas
                candidates = list(self.get_deployment_hexes(unit.allegiance))
        else:
            # Replacements / Activation
            country = self.game_state.countries.get(unit.land)
            if country:
                if allow_territory_wide:
                    candidates = list(country.territories)
                else:
                    # Solamnic conquest exception:
                    # WS units from a Solamnic country can deploy in any still-unconquered
                    # allied Solamnic location (including Tower).
                    if (
                        unit.allegiance == WS
                        and self.game_state._country_has_tag(country, self.game_state.tag_knight_countries)
                        and not country.conquered
                    ):
                        candidates = list(self.game_state.get_solamnic_group_deployment_locations(unit.allegiance))
                    else:
                    # Rule 9: owner cannot deploy into enemy-occupied locations.
                    # Conqueror can deploy from occupied locations (handled for stateless below).
                        for loc in country.locations.values():
                            if loc.coords and self.game_state.can_use_location_for_deployment(country, loc, unit.allegiance):
                                candidates.append(loc.coords)
            else:
                # Handle stateless units (units without land) during REPLACEMENTS phase
                # These units should be deployable in any friendly location
                # Event-driven deployments pass allow_territory_wide to reuse the replacements logic for stateless units.
                if (self.game_state.phase == GamePhase.REPLACEMENTS or allow_territory_wide) and unit.allegiance == self.game_state.active_player:
                    # Rule 9: includes original friendly locations plus conquered occupied locations.
                    for country_obj in self.game_state.countries.values():
                        for loc in country_obj.locations.values():
                            if loc.coords and self.game_state.can_use_location_for_deployment(country_obj, loc, unit.allegiance):
                                candidates.append(loc.coords)

        # 2. Filter based on Unit Type & Terrain
        valid_hexes = []
        country = self.game_state.countries.get(unit.land)

        for col, row in candidates:
            hex_obj = Hex.offset_to_axial(col, row)

            if unit.unit_type == UnitType.FLEET:
                # Rule: Coastal and Port (Deployment) or Port (Replacements)
                if self.game_state.phase == GamePhase.DEPLOYMENT and not country_deployment:
                    if self._is_deployment_fleet_hex(hex_obj):
                        if self.game_state.map.can_stack_move_to([unit], hex_obj):
                            valid_hexes.append((col, row))
                elif country and self.is_valid_fleet_deployment(hex_obj, country):
                    if self.game_state.map.can_stack_move_to([unit], hex_obj):
                        valid_hexes.append((col, row))
            else:
                # Ground Units: Cannot deploy into Ocean
                # (Unless specific amphibious rules exist, but generally no)
                if self.game_state.map.can_unit_land_on_hex(unit, hex_obj):
                    if self.game_state.map.can_stack_move_to([unit], hex_obj):
                        valid_hexes.append((col, row))

        return valid_hexes

    def _is_deployment_fleet_hex(self, hex_obj: Hex) -> bool:
        """Deployment: coastal hexes or ports without country restrictions."""
        if self.game_state.map.is_coastal(hex_obj):
            return True
        loc = self.game_state.map.get_location(hex_obj)
        return bool(loc and isinstance(loc, dict) and loc.get("type") == LocType.PORT.value)

    def deploy_unit(
        self,
        unit,
        target_hex: Hex,
        invasion_deployment_active: bool = False,
        invasion_deployment_allegiance: str | None = None,
        invasion_deployment_country_id: str | None = None,
        highlord_allegiance: str = HL,
    ) -> UnitDeploymentResult:
        if not self.game_state.map.can_unit_land_on_hex(unit, target_hex):
            return UnitDeploymentResult(success=False, error=f"Cannot deploy {unit.id}: invalid terrain.")

        if not self.game_state.map.can_stack_move_to([unit], target_hex):
            return UnitDeploymentResult(success=False, error=f"Cannot deploy {unit.id}: stacking limit or enemy presence.")

        self.game_state.move_unit(unit, target_hex)
        unit.status = UnitState.ACTIVE

        if (
            invasion_deployment_active
            and invasion_deployment_allegiance == highlord_allegiance
            and unit.land == invasion_deployment_country_id
        ):
            unit.movement_points = 0

        return UnitDeploymentResult(success=True)
