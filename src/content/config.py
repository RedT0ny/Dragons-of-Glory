# config.py - Constants moved to constants.py
import os

# --- DEBUG & RUNTIME ---
DEBUG = False
DEFAULT_LANG = "en"
APP_NAME = "Dragons of Glory"
APP_VERSION = "Pre-Alpha 0.22.2"

# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOCALE_DIR = os.path.join(DATA_DIR, "locale")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
AUDIO_DIR = os.path.join(ASSETS_DIR, "audio")
FONTS_DIR = os.path.join(ASSETS_DIR, "font")
ICONS_DIR = os.path.join(ASSETS_DIR, "icon")
IMAGES_DIR = os.path.join(ASSETS_DIR, "img")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")
SAVEGAME_DIR = os.path.join(BASE_DIR, "saves")
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
LIBRA_FONT = os.path.join(FONTS_DIR, "Libra Regular.otf")
LOGO_HL = os.path.join(ICONS_DIR, "logo_hl.png")
LOGO_WS = os.path.join(ICONS_DIR, "logo_ws.png")
LOG_FILE = os.path.join(LOGS_DIR, "qt_last20.log")

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
COVER_PICTURE = os.path.join(IMAGES_DIR, "scenario.jpg")
INTRO_VIDEO = os.path.join(VIDEOS_DIR, "intro.gif")
MAP_IMAGE_PATH = os.path.join(IMAGES_DIR, "map.jpg")
LOCATION_SIZE = 60
MAX_TICKS = 12
OVERLAY_ALPHA = 100
