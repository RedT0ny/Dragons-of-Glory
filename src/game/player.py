import re
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

    def grant_asset(self, asset_id: str, game_state, instance_id: Optional[str] = None):
        """
        Unified method to grant artifacts, resources, or banners.
        
        :param asset_id: The base asset ID (e.g., "dragonarmor") or instance ID (e.g., "dragonarmor_1")
        :param game_state: The current game state
        :param instance_id: Optional unique instance ID (e.g., "dragonarmor_1"). 
                           If not provided, generates one based on existing instances.
        """
        # Extract base asset ID if instance_id looks like "assetname_N"
        # This handles both direct calls with base IDs and restore from save with instance IDs
        base_asset_id = asset_id
        if instance_id is None:
            # Check if asset_id itself looks like an instance ID (ends with _number)
            match = re.match(r'^(.+)_(\d+)$', asset_id)
            if match:
                potential_base = match.group(1)
                # Verify the base exists in the artifact pool
                if potential_base in game_state.artifact_pool:
                    base_asset_id = potential_base
                    instance_id = asset_id  # Use the full ID as instance_id
                # If base doesn't exist, treat asset_id as the base ID and auto-generate instance_id
            else:
                # No instance ID provided and asset_id doesn't look like an instance ID
                # Auto-generate instance ID
                pass
        
        # Look up the blueprint using base_asset_id
        spec = game_state.artifact_pool.get(base_asset_id)
        if not spec:
            print(f"Warning: Asset ID {base_asset_id} not found in catalog.")
            return

        # Generate unique instance ID if not provided
        if instance_id is None:
            # Count existing instances of this asset type
            existing_count = sum(1 for key in self.assets if key.startswith(f"{base_asset_id}_"))
            instance_id = f"{base_asset_id}_{existing_count + 1}"
        
        # Check if this specific instance already exists
        if instance_id in self.assets:
            return  # Already owned

        # Create the live Asset instance via factory so placeholders are materialized.
        from src.content.factory import create_asset_from_spec
        new_asset = create_asset_from_spec(spec, instance_id=instance_id)
        new_asset.owner = self

        self.assets[instance_id] = new_asset
        print(f"Player {self.allegiance} received asset: {spec.id} ({spec.asset_type}) [Instance: {instance_id}]")

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
