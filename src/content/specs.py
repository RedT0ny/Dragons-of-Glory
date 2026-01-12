"""
Defines various data structures for game specifications using dataclass and NamedTuple.

This module outlines the data models for game configurations, including
locations, countries, units, scenarios, saved game states, and map configurations.

Shall only be used by Loader.py to read data from CSV/JSON/YAML files into these structures.

Classes:
- LocationSpec: Represents the details of a specific location on the map.
- CountrySpec: Represents a country and its associated properties.
- UnitSpec: Represents a unit and its various attributes.
- ScenarioSpec: Represents the structure of a game scenario, including map
  subset, events, setup, and victory conditions.
- SaveGameSpec: Represents the structure of saved game state metadata and
  the state of the game world.
- MapConfigSpec: Represents the configuration for a map layout, including
  terrain, dimensions, and special locations.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

@dataclass
class LocationSpec:
    id: str
    loc_type: str
    coords: Tuple[int, int]

@dataclass
class CountrySpec:
    id: str
    capital_id: str
    strength: int
    allegiance: str
    alignment: Tuple[int, int]
    color: str
    locations: List[LocationSpec]
    territories: List[Tuple[int, int]]

@dataclass
class UnitSpec:
    id: str             # The only ID we need (from CSV or generated)
    unit_type: Optional[str]
    race: Optional[str]
    country: Optional[str]
    dragonflight: Optional[str]
    allegiance: Optional[str]
    terrain_affinity: Optional[str]
    combat_rating: Optional[int]
    tactical_rating: Optional[int]
    movement: Optional[int]
    quantity: int = 1
    ordinal: int = 1
    status: str = "inactive"

@dataclass
class ScenarioSpec:
    id: str
    description: str
    map_subset: Optional[Dict[str, List[int]]]
    start_turn: int
    end_turn: int
    initiative_start: str
    possible_events: List[str]
    setup: Dict[str, Any]
    victory_conditions: Dict[str, Any]
    notes: str = "" # Added a default value to prevent errors if notes are missing

@dataclass
class SaveGameSpec:
    metadata: Dict[str, Any]
    world_state: Dict[str, Any]

@dataclass
class MapConfigSpec:
    name: str
    width: int
    height: int
    hex_size: int
    terrain_types: List[str]
    hexsides: Dict[str, List[Any]]
    special_locations: List[LocationSpec]

@dataclass
class ArtifactSpec:
    id: str
    description: str
    bonus: Dict[str, Any]
    requirements: List[Dict[str, Any]]
    is_consumable: bool = False

@dataclass
class EventSpec:
    id: str
    event_type: str # Uses EventType enum values
    description: str
    trigger_conditions: Dict[str, Any] # e.g., {"turn": 10, "requires": ["metal"]}
    effects: Dict[str, Any] # e.g., {"add_units": ["silver_dragon"], "grant_artifact": "dragonlance"}
    allegiance: Optional[str] = None # Who benefits?
    max_occurrences: int = 1  # Default to 1 (one-time event)