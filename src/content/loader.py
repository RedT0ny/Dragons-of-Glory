import os, json
from pathlib import Path
from typing import Any, Dict
try:
    import yaml  # Add PyYAML in requirements if not present
    _has_yaml = True
except ImportError:
    _has_yaml = False

def load_data(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in (".yaml", ".yml"):
        if not _has_yaml:
            raise RuntimeError("PyYAML not installed")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    elif path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise ValueError(f"Unsupported data format: {path.suffix}")

# Logic to be added to your loader/game_state initialization:
def load_map_features(hex_grid, data):
    for hex_coord, terrain in data['terrain'].items():
        hex_grid.grid[hex_coord] = terrain
        
    for hexside, side_type in data['hexsides'].items():
        # hexside would be a tuple of two adjacent hex coordinates
        hex_grid.hexside_data[hexside] = side_type
