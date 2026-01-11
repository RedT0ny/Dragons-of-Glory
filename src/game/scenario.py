from typing import List, Dict, Any, Set
from collections import defaultdict
from src.content.specs import ScenarioSpec, UnitSpec

class Scenario:
    def __init__(self, spec: ScenarioSpec, global_unit_pool: List[UnitSpec], all_countries: Dict[str, Any]):
        self.spec = spec
        self.all_countries = all_countries

        # 1. Expand the pool: Turn 'quantity' from CSV into individual UnitSpec objects
        self._expanded_pool = []
        for s in global_unit_pool:
            for i in range(1, s.quantity + 1):
                new_id = f"{s.id}_{i}" if s.quantity > 1 else s.id
                # Create a copy with the unique ID and ordinal
                # This logic is moved here from resolve_scenario_units
                self._expanded_pool.append(UnitSpec(
                    id=new_id, unit_type=s.unit_type, race=s.race,
                    country=s.country, dragonflight=s.dragonflight,
                    allegiance=s.allegiance, terrain_affinity=s.terrain_affinity,
                    combat_rating=s.combat_rating, tactical_rating=s.tactical_rating,
                    movement=s.movement, quantity=1, ordinal=i
                ))

        # 2. Index the pool for lightning-fast resolution
        self._idx = {
            "id": {u.id: u for u in self._expanded_pool},
            "country": defaultdict(list),
            "df": defaultdict(list)
        }
        for u in self._expanded_pool:
            if u.country: self._idx["country"][u.country.lower()].append(u)
            if u.dragonflight: self._idx["df"][u.dragonflight.lower()].append(u)

    def get_deployment_hexes(self, allegiance: str) -> Set[tuple]:
        """
        Returns a set of (x, y) coordinates where a player can deploy.
        Handles the simplification logic: if deployment_area is null, 
        it uses all territories of the countries listed for that allegiance.
        """
        player_setup = self.spec.setup.get(allegiance, {})
        area_spec = player_setup.get("deployment_area")

        if area_spec is None:
            # Simplification: Use all countries assigned to this player
            countries_to_use = player_setup.get("countries", {}).keys()
        else:
            # Use specific countries defined in the deployment_area
            countries_to_use = area_spec.get("countries", [])

        hexes = set()
        for cid in countries_to_use:
            if cid in self.all_countries:
                hexes.update(self.all_countries[cid].territories)
        return hexes

    def get_starting_units(self, allegiance: str) -> List[UnitSpec]:
        """
        The intelligence is now here. We look at the 'setup' dictionary
        and use our index to find the matching units.
        """
        player_setup = self.spec.setup.get(allegiance, {})
        selected = []

        # Logic for 'units: all' by country
        for country_id, config in player_setup.get("countries", {}).items():
            lc = country_id.lower()
            if config == "all" or (isinstance(config, dict) and config.get("units") == "all"):
                # Use our index instead of looping over everything
                selected.extend(self._idx["country"].get(lc, []))
                # Also check if it's a dragonflight color
                selected.extend(self._idx["df"].get(lc, []))

        # Logic for Explicit units
        for unit_id in player_setup.get("explicit_units", []):
            u = self._idx["id"].get(unit_id.lower())
            if u: selected.append(u)

        return selected

    @property
    def map_bounds(self):
        """Returns the subset range or full map defaults."""
        if self.spec.map_subset:
            return self.spec.map_subset
        return {"x_range": [0, 64], "y_range": [0, 52]}
