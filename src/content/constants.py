"""
Game constants - mechanical, and data constants.
No dependencies on other game modules.
"""

# --- ALLEGIANCES ---
WS = "whitestone"
HL = "highlord"
NEUTRAL = "neutral"

# --- COUNTRY TAGS (data/countries.yaml) ---
TAG_KNIGHT_COUNTRIES = "knight_countries"
# Countries that can only join a side via an event or a military invasion (never the diplomacy roll).
TAG_EVENT_INVASION_ONLY = "event_invasion_only"

# --- DRAGONFLIGHTS ---
EVIL_DRAGONFLIGHTS = {"red", "blue", "green", "black", "white"}
GOOD_DRAGONFLIGHTS = {"gold", "silver", "bronze", "copper", "brass"}
DRAGONFLIGHTS = EVIL_DRAGONFLIGHTS | GOOD_DRAGONFLIGHTS

# --- GAME MECHANICS ---
MAX_UNITS_PER_HEX = 2
DEFAULT_MOVEMENT_POINTS = 5

# --- COMBAT RULES ---
MIN_COMBAT_ROLL = -5
MAX_COMBAT_ROLL = 16
MAX_ODDS_RATIO = 6.0
MIN_ODDS_RATIO = 0.33

# --- DIRECTION MAPPING (game logic) ---
DIRECTION_MAP = {
    "E":  0,
    "NE": 1,
    "NW": 2,
    "W":  3,
    "SW": 4,
    "SE": 5
}
