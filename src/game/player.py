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
        self.assets: Dict[str, Any] = {} # ID -> Asset Instance
        self.prerequisites: Set[str] = set(spec.pre_req or []) # Track pre-requirements for events, like artifacts

        # Legacy/Transition: Init assets from spec artifacts if present
        # Note: This requires game_state to resolve specs, usually done in initialization phase
        # For now we initialize empty and let GameState populate it

    def add_country(self, country: Country):
        self.controlled_countries[country.spec.id] = country

    def set_ai(self, enabled: bool):
        """Runtime toggle for AI control."""
        self.is_ai = enabled

    def grant_asset(self, asset_id: str, game_state):
        """
        Unified method to grant artifacts, resources, or banners.
        """
        if asset_id in self.assets:
            return # Already owned

        # Look up the blueprint
        spec = game_state.artifact_pool.get(asset_id)
        if not spec:
            print(f"Warning: Asset ID {asset_id} not found in catalog.")
            return

        # Create the live Asset instance
        from src.game.event import Asset
        new_asset = Asset(spec)
        new_asset.owner = self

        self.assets[asset_id] = new_asset
        print(f"Player {self.allegiance} received asset: {spec.id} ({spec.asset_type})")

    def has_asset(self, asset_id: str) -> bool:
        return asset_id in self.assets

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
