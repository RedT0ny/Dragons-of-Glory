from typing import Set, Dict, Any, Optional, Callable, List, Union
from src.content.specs import PlayerSpec
from src.game.country import Country

class Player:
    def __init__(self, spec: PlayerSpec):
        self.spec = spec
        self.allegiance = spec.allegiance
        self.controlled_countries: Dict[str, Country] = {}
        self.is_ai = spec.is_ai

        # Runtime Sets
        self.artifacts: Set[str] = set(spec.artifacts or [])
        self.prerequisites: Set[str] = set(spec.pre_req or []) # Track pre-requirements for events, like artifacts

    def add_country(self, country: Country):
        self.controlled_countries[country.spec.id] = country

    def set_ai(self, enabled: bool):
        """Runtime toggle for AI control."""
        self.is_ai = enabled

    def add_artifact(self, artifact_id: str):
        self.artifacts.add(artifact_id)

    def remove_artifact(self, artifact_id: str):
        if artifact_id in self.artifacts:
            self.artifacts.remove(artifact_id)

    def has_artifact(self, artifact_id: str) -> bool:
        return artifact_id in self.artifacts

    def get_deployment_hexes(self, all_countries: Dict[str, Country], is_hex_in_bounds: Callable[[int, int], bool]) -> Set[tuple]:
        """
        Calculates valid deployment hexes based on spec and controlled countries.
        """
        hexes = set()
        area_spec = self.spec.deployment_area

        # Case 1: deployment_area is None -> Use all controlled countries (from setup)
        if area_spec is None:
            for country in self.controlled_countries.values():
                hexes.update(country.territories)
            return hexes

        # Case 2: deployment_area is a Dictionary
        if isinstance(area_spec, dict):
            # 'countries' key: list of country IDs to use
            countries_to_use = area_spec.get("countries", [])
            for cid in countries_to_use:
                if cid in all_countries:
                    hexes.update(all_countries[cid].territories)
            
            # 'coords' or 'hexes' keys: explicit lists of coordinates
            for key in ["coords", "hexes"]:
                coords_list = area_spec.get(key)
                if isinstance(coords_list, list):
                    for item in coords_list:
                        if isinstance(item, (list, tuple)) and len(item) == 2:
                            coord = tuple(item)
                            if is_hex_in_bounds(*coord):
                                hexes.add(coord)

        # Case 3: deployment_area is a List (mixed coords and country IDs)
        elif isinstance(area_spec, list):
            for item in area_spec:
                if isinstance(item, str): # Country ID
                    if item in all_countries:
                        hexes.update(all_countries[item].territories)
                elif isinstance(item, (list, tuple)) and len(item) == 2: # Coordinate
                    coord = tuple(item)
                    if is_hex_in_bounds(*coord):
                        hexes.add(coord)

        return hexes
