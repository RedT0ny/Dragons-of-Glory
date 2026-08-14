"""
Winter weather rules (winter campaign turns).

Calendar turns whose period is "Winter" (every 5th turn) trigger seasonal rules
inside the map's winter region:

- **Fleet survival**: every fleet that moves (or tries to move) inside the winter
  region rolls a d6; on a 1 the ice breaks and the fleet sinks (eliminated, with
  normal leader-escape processing).  Resolved in ``MovementService``.
- **Frozen rivers**: river/deep-river hexsides inside the winter region freeze.
  Ground armies cross them at plain movement cost (no +1 ford penalty), supply
  lines and ZOC can trace across them, and attackers no longer suffer the
  crossing-river combat DRM.  Fleets, however, cannot enter frozen deep rivers.
- **Blocked passes**: mountain passes inside the winter region are snowed in and
  impassable to ground armies; they block supply lines and ZOC and never confer
  the crossing-pass combat bonus.
- **Wing MP**: wings in the winter region have their movement points halved
  (min 1) at the start of each movement phase.
- **Interception**: in the winter region only adjacent interceptors (dist == 1)
  can be spotted, at 50% (non-winter: 100% adjacent / 50% at distance 2).

The winter region is defined in ``data/map_config.yaml`` under
``master_map.winter`` as a bounding box in master-map offset coordinates::

    winter:
      min_col: 0
      max_col: 57
      min_row: 0
      max_row: 39

Hexes outside the box (far south / far east) never experience winter weather.
"""

from src.content.specs import HexsideType
from src.game.map import Hex


class WinterService:
    """Encapsulates the winter-season and winter-region queries."""

    def __init__(self, game_state):
        self.game_state = game_state
        self._forced_winter = None

    def override_winter(self, value):
        """Force/enable or disable winter regardless of the calendar (tests)."""
        self._forced_winter = bool(value)

    # --- Season ---

    def is_winter(self) -> bool:
        """True when the current calendar turn is a winter turn."""
        if self._forced_winter is not None:
            return self._forced_winter
        calendar = getattr(self.game_state, "calendar", None)
        turn = getattr(self.game_state, "turn", None)
        if calendar is None or not turn:
            return False
        try:
            spec = calendar.get_spec(int(turn))
        except Exception:
            return False
        period = str(getattr(spec, "period", "")).strip().lower()
        return period == "winter"

    # --- Region ---

    def _winter_config(self):
        board = getattr(self.game_state, "map", None)
        if board is None:
            return {}
        return getattr(board, "winter_region", None) or {}

    def is_winter_zone(self, hex_coord) -> bool:
        """True if the hex lies inside the winter region (geometry only)."""
        if hex_coord is None:
            return False
        cfg = self._winter_config()
        board = getattr(self.game_state, "map", None)
        if board is None:
            return False
        try:
            master_q, master_r = board.to_master_coords(hex_coord.q, hex_coord.r)
            col, row = Hex(master_q, master_r).axial_to_offset()
        except Exception:
            return False

        def _bound(key, default):
            raw = cfg.get(key)
            if raw is None:
                return default
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default

        min_col = _bound("min_col", -10**9)
        max_col = _bound("max_col", 10**9)
        min_row = _bound("min_row", -10**9)
        max_row = _bound("max_row", 10**9)
        return min_col <= col <= max_col and min_row <= row <= max_row

    def is_affected_hex(self, hex_coord) -> bool:
        """True when it is winter AND the hex is inside the winter region."""
        return bool(self.is_winter() and hex_coord is not None and self.is_winter_zone(hex_coord))

    # --- Hexside weather ---

    def is_frozen_hexside(self, from_hex, to_hex) -> bool:
        """True when the river hexside between the two hexes is frozen solid."""
        if not self.is_winter():
            return False
        if not self.is_winter_zone(from_hex) or not self.is_winter_zone(to_hex):
            return False
        board = getattr(self.game_state, "map", None)
        if board is None:
            return False
        hexside = board.get_effective_hexside(from_hex, to_hex)
        return hexside in (HexsideType.RIVER, HexsideType.DEEP_RIVER)

    def is_pass_blocked(self, from_hex, to_hex) -> bool:
        """True when the mountain pass between the two hexes is snowed in."""
        if not self.is_winter():
            return False
        if not self.is_winter_zone(from_hex) or not self.is_winter_zone(to_hex):
            return False
        board = getattr(self.game_state, "map", None)
        if board is None:
            return False
        hexside = board.get_effective_hexside(from_hex, to_hex)
        return hexside == HexsideType.PASS
