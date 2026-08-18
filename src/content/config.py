# config.py - Constants moved to constants.py
import math
import os
import platform
import sys

# --- DEBUG & RUNTIME ---
DEBUG = False
DEFAULT_LANG = "en"
APP_NAME = "Dragons of Glory"
APP_VERSION = "0.55.1-beta"

# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _user_data_dir():
    """Return a stable, user-writable directory for saves and logs.

    When running from a PyInstaller bundle, the frozen exe is extracted to a
    temporary folder that is cleaned up on exit.  We redirect user data to a
    proper per-platform location so saves persist across runs.
    """
    if getattr(sys, 'frozen', False):
        if platform.system() == "Windows":
            base = os.path.expandvars(r"%LOCALAPPDATA%")
        elif platform.system() == "Darwin":
            base = os.path.join(os.path.expanduser("~"),
                                "Library", "Application Support")
        else:  # Linux / other
            base = os.environ.get(
                "XDG_DATA_HOME",
                os.path.join(os.path.expanduser("~"), ".local", "share"))
        return os.path.join(base, APP_NAME)
    return BASE_DIR


USER_DATA_DIR = _user_data_dir()

DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(USER_DATA_DIR, "logs")
LOCALE_DIR = os.path.join(DATA_DIR, "locale")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
AUDIO_DIR = os.path.join(ASSETS_DIR, "audio")
DOC_DIR = os.path.join(ASSETS_DIR, "doc")
FONTS_DIR = os.path.join(ASSETS_DIR, "font")
ICONS_DIR = os.path.join(ASSETS_DIR, "icon")
IMAGES_DIR = os.path.join(ASSETS_DIR, "img")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")
SAVEGAME_DIR = os.path.join(USER_DATA_DIR, "saves")
VIDEOS_DIR = os.path.join(ASSETS_DIR, "video")

# --- DATA FILES ---
COUNTRIES_DATA = os.path.join(DATA_DIR, "countries.yaml")
CRT_DATA = os.path.join(DATA_DIR, "crt.csv")
MAP_CONFIG_DATA = os.path.join(DATA_DIR, "map_config.yaml")
MAP_TERRAIN_DATA = os.path.join(DATA_DIR, "ansalon_map.csv")
UNITS_DATA = os.path.join(DATA_DIR, "units.csv")
EVENTS_DATA = os.path.join(DATA_DIR, "events.yaml")
ARTIFACTS_DATA = os.path.join(DATA_DIR, "artifacts.yaml")
CALENDAR_DATA = os.path.join(DATA_DIR, "calendar.csv")
AI_STANCE_DATA = os.path.join(DATA_DIR, "ai_stance.csv")
LIBRA_FONT = os.path.join(FONTS_DIR, "Libra Regular.otf")
LOGO_HL = os.path.join(ICONS_DIR, "logo_hl.png")
LOGO_WS = os.path.join(ICONS_DIR, "logo_ws.png")
LOG_FILE = os.path.join(LOGS_DIR, "dog.log")
MANUAL = os.path.join(DOC_DIR, "manual.pdf")
ADVANCED_RULES = os.path.join(DOC_DIR, "advanced_rules.pdf")
HOUSE_RULES = os.path.join(DOC_DIR, "house_rules.pdf")
ICON_INITIATIVE = os.path.join(ICONS_DIR, "initiative_chit.svg")

# --- GUI SETTINGS ---
HEX_RADIUS = 61.77
MAP_WIDTH = 65
MAP_HEIGHT = 53
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
X_OFFSET = 244
Y_OFFSET = 198
UNIT_SIZE = HEX_RADIUS * 0.45
UNIT_ICON_SIZE = 60
GAME_ICON = os.path.join(ICONS_DIR, "DOG_icon.ico")
COVER_PICTURE = os.path.join(IMAGES_DIR, "scenario.jpg")
INTRO_VIDEO = os.path.join(VIDEOS_DIR, "intro.mp4")
MAP_IMAGE_PATH = os.path.join(IMAGES_DIR, "map.jpg")
LOCATION_SIZE = 60
MAX_TICKS = 12
OVERLAY_ALPHA = 100
ZOOM_MULTIPLIER = math.sqrt(2.0)