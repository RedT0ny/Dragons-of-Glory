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
from enum import Enum, auto
from src.content.constants import WS, HL, NEUTRAL

@dataclass
class LocationSpec:
    id: str
    loc_type: str
    coords: Tuple[int, int]
    is_capital: bool = False

@dataclass
class CountrySpec:
    id: str
    capital_id: str
    strength: int
    allegiance: str
    alignment: Tuple[int, int]  # alignment: Tuple (WS, HL) representing activation modifiers.
    color: str
    locations: List[LocationSpec]
    territories: List[Tuple[int, int]]

@dataclass
class UnitSpec:
    """
    Blueprint for all units in the game.

        :ivar id: The name of the unit.
        :type id: str
        :ivar unit_type: The type of the unit ('infantry', 'cavalry', 'general', 'admiral', 'hero', 'fleet', 'wing').
        :type unit_type: UnitType
        :ivar race: The race of the unit (e.g., 'draconian', 'dragon', 'goblin', 'hogboblin', 'human', 'solamnic', 'dwarf', 'elf', 'griffon', 'kender', 'minotaur', 'ogre', 'pegasus', 'thanoi', 'undead').
        :type race: UnitRace
        :ivar country: The country the unit belongs to.
        :type country: str
        :ivar dragonflight: The dragonflight the unit belongs to.
        :type dragonflight: str
        :ivar allegiance: The allegiance of the unit (e.g., 'Highlord', 'Neutral', 'Whitesone').
        :type allegiance: str
        :ivar terrain_affinity: The terrain affinity of the unit (e.g., 'mountain', 'desert', 'swamp').
        :type terrain_affinity: str
        :ivar combat_rating: The combat rating of the unit.
        :type combat_rating: int
        :ivar tactical_rating: The tactical rating of the unit.
        :type tactical_rating: int
        :ivar movement: The movement points available for the unit.
        :type movement: int
        :ivar status: The current status of the unit (e.g., 'inactive', 'active', 'depleted', 'reserve', 'destroyed').
        :type status: UnitState
    """
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
    """
    Blueprint for game scenarios and campaigns.

        :ivar id: The name of the scenario.
        :ivar description: A brief description of the scenario.
        :ivar map_subset: A dictionary mapping map names to lists of hex indices.
        :ivar start_turn: The turn number when the scenario starts.
        :ivar end_turn: The turn number when the scenario ends.
        :ivar initiative_start: The unit ID that starts the initiative phase.
        :ivar active_events: A list of event IDs that are active during the scenario.
        :ivar setup: A dictionary containing setup configurations for the scenario.
        :ivar victory_conditions: A dictionary defining victory conditions for the scenario.
        :ivar picture: A filename for a picture associated with the scenario (default: "scenario.jpg").
        :ivar notes: Additional notes about the scenario (default: "").
    """
    id: str
    description: str
    map_subset: Optional[Dict[str, List[int]]]
    start_turn: int
    end_turn: int
    initiative_start: str
    active_events: List[str]
    setup: Dict[str, Any]
    victory_conditions: Dict[str, Any]
    picture: str = "scenario.jpg"  # Added field with a default fallback
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

# --- ENUMS ---
class EventType(Enum):
    PLAYER_BONUS = "bonus"
    REINFORCEMENTS = "units"
    PREREQUISITE = "pre_req"
    ARTIFACT = "artifact"

class UnitRace(Enum):
    DWARF = "dwarf"
    ELF = "elf"
    OGRE = "ogre"
    HUMAN = "human"
    DRACONIAN = "draconian"
    DRAGON = "dragon"
    GOBLIN = "goblin"
    HOGBOBLIN = "hogboblin"
    KENDER = "kender"
    PEGASUS = "pegasus"
    THANOI = "thanoi"
    UNDEAD = "undead"
    GRIFFON = "griffon"
    MINOTAUR = "minotaur"
    SOLAMNIC = "solamnic"
    MAGIC = "magic"

class UnitState(Enum):
    INACTIVE = auto()
    READY = auto()      # Ready to be deployed (reinforcement or rebuilt)
    ACTIVE = auto()     # On map, full strength
    DEPLETED = auto()   # On map, reduced strength
    RESERVE = auto()    # In replacement pool (eliminated but recyclable)
    DESTROYED = auto()  # Permanently out of the game

    @classmethod
    def on_map_states(cls):
        return {cls.ACTIVE, cls.DEPLETED}

class GamePhase(Enum):
    DEPLOYMENT = auto()        # Step 0: Initial Deployment phase (only once)
    REPLACEMENTS = auto()      # Step 1: Replacements
    STRATEGIC_EVENTS = auto()  # Step 2: Strategic Events
    ACTIVATION = auto()        # Step 3: Country activation by diplomacy
    INITIATIVE = auto()        # Step 4: Initiative roll
    MOVEMENT = auto()          # Step 5 & 7 (Movement portion)
    COMBAT = auto()            # Step 6 & 7 (Combat portion)
    END_TURN = auto()          # Step 8: End of turn cleanup

class UnitType(Enum):
    INFANTRY = "inf"
    CAVALRY = "cav"
    WIZARD = "wizard"
    GENERAL = "general"
    ADMIRAL = "admiral"
    EMPEROR = "emperor"
    FLEET = "fleet"
    CITADEL = "citadel"
    HERO = "hero"
    WING = "wing"
    HIGHLORD = "highlord"

class HexDirection(Enum):
    NORTH_EAST = 0
    EAST = 1
    SOUTH_EAST = 2
    SOUTH_WEST = 3
    WEST = 4
    NORTH_WEST = 5

class RequirementType(Enum):
    RACE = "race"
    TRAIT = "trait"
    ITEM = "item"
    ALLEGIANCE = "allegiance"
    UNIT_TYPE = "unit_type"
    CUSTOM = "custom"

# --- ARTIFACT CONFIG ---
ARTIFACT_REQUIREMENTS = {
    "race_requirements": {
        "solamnic": UnitRace.SOLAMNIC,
        "draconian": UnitRace.DRACONIAN,
        "dragon": UnitRace.DRAGON,
        "elf": UnitRace.ELF,
        "dwarf": UnitRace.DWARF,
        "human": UnitRace.HUMAN,
        "kender": UnitRace.KENDER,
        "ogre": UnitRace.OGRE,
    },
    "trait_requirements": {
        "has_silver_arm": lambda unit: hasattr(unit, 'traits') and 'silver_arm' in unit.traits,
        "is_leader": lambda unit: hasattr(unit, 'unit_type') and unit.unit_type in [UnitType.GENERAL, UnitType.ADMIRAL, UnitType.EMPEROR],
        "is_magical": lambda unit: hasattr(unit, 'unit_type') and unit.unit_type == UnitType.WIZARD,
    },
    "allegiance_requirements": {
        "whitestone": WS,
        "highlord": HL,
        "neutral": NEUTRAL,
    }
}
