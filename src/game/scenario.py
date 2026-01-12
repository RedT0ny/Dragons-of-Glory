from typing import List, Dict, Any, Set
from collections import defaultdict
# REMOVED: from src.content.specs import ScenarioSpec, UnitSpec

class Scenario:
    def __init__(self, scenario_id: str, description: str, units: List[Any], countries: Dict[str, Any], setup: Dict[str, Any], map_subset: Dict[str, Any] = None):
        """
        Scenario now takes pre-processed lists and raw configuration.
        It doesn't know what a 'Spec' is.
        """
        self.id = scenario_id
        self.description = description
        self.units = units
        self.countries = countries
        self.setup = setup
        self._map_subset = map_subset

        # 1. Indexing for fast resolution (Logic remains, but works on live objects)
        self._idx = {
            "id": {u.id: u for u in self.units},
            "country": defaultdict(list),
            "df": defaultdict(list)
        }
        for u in self.units:
            if hasattr(u, 'land') and u.land: self._idx["country"][u.land.lower()].append(u)
            if hasattr(u, 'dragonflight') and u.dragonflight: self._idx["df"][u.dragonflight.lower()].append(u)

    # ... existing get_deployment_hexes and get_starting_units methods ...
    # They stay the same but reference self.setup and self.all_countries instead of self.spec
# ... existing code ...
    @property
    def map_bounds(self):
        """Returns the subset range or full map defaults."""
        if self._map_subset:
            return self._map_subset
        return {"x_range": [0, 64], "y_range": [0, 52]}
