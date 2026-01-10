from typing import List, Dict, Any, Set
from src.content.loader import ScenarioSpec

class Scenario:
    def __init__(self, spec: ScenarioSpec, all_countries: Dict[str, Any], all_units: List[Dict[str, Any]]):
        self.spec = spec
        self.all_countries = all_countries
        self.all_units = all_units

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

    def get_starting_units(self, allegiance: str) -> List[Dict[str, Any]]:
        """
        Resolves 'units: all' and explicit units into a flat list of unit data.
        """
        player_setup = self.spec.setup.get(allegiance, {})
        resolved_units = []

        # 1. Handle Country-based units
        for country_id, config in player_setup.get("countries", {}).items():
            if config == "all" or (isinstance(config, dict) and config.get("units") == "all"):
                # Filter units.csv for this country
                resolved_units.extend([
                    u for u in self.all_units if u.get('land') == country_id
                ])
            elif isinstance(config, dict) and "units_by_type" in config:
                # Handle specific quantities (like Scenario 1's 4 inf, 1 cav)
                # Logic to pick N units of type T from the pool goes here
                pass

        # 2. Handle Explicit units (Leaders, Wizards)
        explicit_ids = player_setup.get("explicit_units", [])
        resolved_units.extend([
            u for u in self.all_units if u.get('id') in explicit_ids
        ])

        return resolved_units

    @property
    def map_bounds(self):
        """Returns the subset range or full map defaults."""
        if self.spec.map_subset:
            return self.spec.map_subset
        return {"x_range": [0, 64], "y_range": [0, 52]}
