"""
Game constants - visual, mechanical, and data constants.
No dependencies on other game modules.
"""

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

# ============ TERRAIN VISUALS ============
TERRAIN_VISUALS = {
    "grassland": {"color": QColor(238, 244, 215), "pattern": Qt.Dense7Pattern},
    "steppe": {"color": QColor(180, 190, 100), "pattern": Qt.Dense7Pattern},
    "forest": {"color": QColor(34, 139, 34), "pattern": Qt.Dense7Pattern},
    "jungle": {"color": QColor(0, 85, 0), "pattern": Qt.Dense7Pattern},
    "mountain": {"color": QColor(139, 115, 85), "pattern": Qt.Dense7Pattern},
    "swamp": {"color": QColor(85, 107, 47), "pattern": Qt.Dense7Pattern},
    "desert": {"color": QColor(244, 164, 96), "pattern": Qt.Dense7Pattern},
    "ocean": {"color": QColor(135, 206, 250), "pattern": Qt.Dense7Pattern},
    "maelstrom": {"color": QColor(130, 9, 9), "pattern": Qt.Dense7Pattern},
    "glacier": {"color": QColor(231, 173, 255), "pattern": Qt.Dense7Pattern},
}

HEXSIDE_COLORS = {
    "river": QColor(100, 149, 237, 200),
    "deep_river": QColor(0, 0, 139, 255),
    "mountain": QColor(139, 69, 19, 200),
    "pass": QColor(255, 215, 0, 255),
    "bridge": QColor(255, 69, 0, 255)
}

# ============ UI COLORS ============
UI_COLORS = {
    "selected_hex": QColor(255, 255, 0, 100),      # Yellow selection
    "hover_hex": QColor(255, 255, 255, 50),        # White hover
    "movement_range": QColor(0, 255, 0, 30),       # Green movement area
    "attack_range": QColor(255, 0, 0, 30),         # Red attack area
    "reachable_hex": QColor(100, 250, 100, 80),    # Bright green reachable
    "unreachable_hex": QColor(250, 100, 100, 80),  # Red unreachable
    "highlighted_hex": QColor(255, 255, 0, 100),   # Selected Hex
    "neutral_warning_hex": QColor(255, 80, 80, 120)
}

# --- ALLEGIANCES ---
WS = "whitestone"
HL = "highlord"
NEUTRAL = "neutral"

# --- DRAGON FLIGHTS ---
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
