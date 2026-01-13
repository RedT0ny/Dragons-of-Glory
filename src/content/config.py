import os
from enum import Enum, auto

# --- PATHS ---
# Get the absolute path to the project root (Dragons-of-Glory/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(BASE_DIR, "data")
LOCALE_DIR = os.path.join(DATA_DIR, "locale")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "font")
ICONS_DIR = os.path.join(ASSETS_DIR, "icon")
IMAGES_DIR = os.path.join(ASSETS_DIR, "img")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")
SAVEGAME_DIR = os.path.join(BASE_DIR, "saves")

# --- DATA FILES ---
COUNTRIES_DATA = os.path.join(DATA_DIR, "countries.yaml")
CRT_DATA = os.path.join(DATA_DIR, "crt.csv")
MAP_CONFIG_DATA = os.path.join(DATA_DIR, "map_config.yaml")
MAP_TERRAIN_DATA = os.path.join(DATA_DIR, "ansalon_map.csv")
UNITS_DATA = os.path.join(DATA_DIR, "units.csv")
EVENTS_DATA = os.path.join(DATA_DIR, "events.yaml")
ARTIFACTS_DATA = os.path.join(DATA_DIR, "artifacts.yaml")

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
    ACTIVE = auto()
    DEPLETED = auto()
    RESERVE = auto()
    DESTROYED = auto()

    @classmethod
    def on_map_states(cls):
        return {cls.ACTIVE, cls.DEPLETED}

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

DRAGONFLIGHTS = {"red", "blue", "green", "black", "white"}

# --- ALLEGIANCES ---
WS = "whitestone"
HL = "highlord"
NEUTRAL = "neutral"

# --- SETTINGS ---
DEFAULT_LANG = "en"
APP_NAME = "Dragons of Glory"
# Mappings for pointy-top axial neighbors
DIRECTION_MAP = {
    "E":  0,
    "NE": 1,
    "NW": 2,
    "W":  3,
    "SW": 4,
    "SE": 5
}

# --- COMBAT SETTINGS ---
MIN_COMBAT_ROLL = -5
MAX_COMBAT_ROLL = 16
MAX_ODDS_RATIO = 6.0
MIN_ODDS_RATIO = 0.33

# --- GUI SETTINGS ---
# These are only used by the View (gui/ folder)
HEX_RADIUS = 11.15
MAP_WIDTH = 65
MAP_HEIGHT = 53
SCREEN_WIDTH = 1400
SCREEN_HEIGHT = 900
X_OFFSET = 30
Y_OFFSET = 30
UNIT_ICON_SIZE = 20
COVER_PICTURE = os.path.join(IMAGES_DIR, "cover.png")
MAP_IMAGE_PATH = os.path.join(IMAGES_DIR, "ansalon_baseline.jpg")

# --- GAME CONSTANTS ---
MAX_UNITS_PER_HEX = 2
DEFAULT_MOVEMENT_POINTS = 5  # Example for Rule 5

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


