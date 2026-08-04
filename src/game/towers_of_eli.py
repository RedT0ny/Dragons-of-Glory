"""
Towers of E'li naval-defense rule.

Rule (Dragonlance / DoG variant): fleets entering either tower hex must stop;
each intact tower fires two shots at enemy fleets (hit on d10 <= 4), modeled as
fleet depletion (ACTIVE -> DEPLETED -> RESERVE). A tower is permanently
destroyed once an enemy army/wing occupies its hex.

Control: the towers belong to Silvanesti. While the silvanesti country is
neutral they are independent and fire at any Whitestone/Highlord fleet. Once
Silvanesti is activated to a side, the towers defend that side and fire only at
its enemy.
"""

import random

from src.content.constants import HL, NEUTRAL, WS
from src.content.specs import UnitState
from src.content.tools import TextFormatter
from src.game.map import Hex

TOWER_IDS = ("west_eli", "east_eli")
SHOTS_PER_TOWER = 2
HIT_THRESHOLD = 4  # d10 <= 4 is a hit


class TowersOfEliService:
    """Handles the naval-defense towers at the mouth of the E'li river."""

    def __init__(self, game_state):
        self.game_state = game_state

    # --- Location helpers ---

    def is_tower(self, loc) -> bool:
        return bool(loc and getattr(loc, "id", None) in TOWER_IDS)

    def is_tower_hex(self, hex_coord) -> bool:
        return self.is_tower(self.get_tower(hex_coord))

    def get_tower(self, hex_coord):
        """Returns the tower Location at the hex, or None."""
        if not self.game_state.map or not hex_coord:
            return None
        loc = self.game_state.map.get_location(hex_coord)
        if self.is_tower(loc):
            return loc
        return None

    def tower_is_destroyed(self, loc) -> bool:
        return bool(self.is_tower(loc) and getattr(loc, "defense_destroyed", False))

    def mark_tower_destroyed(self, loc):
        """Permanently disables a tower."""
        if self.is_tower(loc):
            loc.defense_destroyed = True

    # --- Control ---

    def defense_side(self):
        """Side the towers defend (WS/HL), or None if independent."""
        country = self.game_state.countries.get("silvanesti")
        if not country:
            return None
        allegiance = getattr(country, "allegiance", NEUTRAL)
        return allegiance if allegiance in (WS, HL) else None

    def tower_fires_at(self, loc, fleet_allegiance: str) -> bool:
        """True if an intact, un-occupied tower fires at a fleet of this side."""
        if not self.is_tower(loc) or self.tower_is_destroyed(loc):
            return False
        if fleet_allegiance not in (WS, HL):
            return False
        if self.tower_is_enemy_occupied(loc):
            return False
        side = self.defense_side()
        if side is None:
            return True  # independent: fires at any side
        return fleet_allegiance != side

    # --- Occupation ---

    def tower_is_enemy_occupied(self, loc) -> bool:
        """True if an enemy army/wing currently occupies the tower hex.

        Scans live units (not just loc.occupier) because occupiers are only
        refreshed after combat resolution.
        """
        if not loc or not loc.coords:
            return False
        hex_obj = Hex.offset_to_axial(*loc.coords)
        side = self.defense_side()
        for unit in self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r):
            if not getattr(unit, "is_on_map", False):
                continue
            if not (unit.is_army() or unit.is_wing()):
                continue
            if unit.allegiance == NEUTRAL:
                continue
            if side is None:
                if unit.allegiance in (WS, HL):
                    return True
            elif unit.allegiance != side and unit.allegiance in (WS, HL):
                return True
        return False

    def mark_tower_destroyed_if_enemy(self, loc) -> bool:
        """Destroys the tower when an enemy occupies it. Returns True if so."""
        if not self.is_tower(loc) or self.tower_is_destroyed(loc):
            return False
        if self.tower_is_enemy_occupied(loc):
            self.mark_tower_destroyed(loc)
            print(f"Tower of E'li ({loc.id}) captured and destroyed.")
            return True
        return False

    # --- Firing ---

    def resolve_tower_shots(self, hex_coord, roll_d10_fn=None) -> list:
        """Fires SHOTS_PER_TOWER shots at enemy fleets in the tower hex.

        Returns a list of human-readable message strings.
        """
        loc = self.get_tower(hex_coord)
        if not loc or self.tower_is_destroyed(loc):
            return []

        hex_obj = Hex.offset_to_axial(*loc.coords)
        fleets = [
            u
            for u in self.game_state.map.get_units_in_hex(hex_obj.q, hex_obj.r)
            if u.is_fleet() and getattr(u, "is_on_map", False)
        ]
        if not fleets:
            return []

        roll_d10 = roll_d10_fn or (lambda: random.randint(1, 10))
        messages = []
        tower_name = f"Tower of E'li ({loc.id})"
        for _ in range(SHOTS_PER_TOWER):
            targets = [
                f for f in fleets if self.tower_fires_at(loc, f.allegiance) and f.is_on_map
            ]
            if not targets:
                break
            fleet = random.choice(targets)
            fleet_name = TextFormatter.format_unit_log_string(fleet)
            if roll_d10() <= HIT_THRESHOLD:
                before = fleet.status
                self.game_state.damage_unit(fleet, mode="deplete")
                if before == UnitState.ACTIVE:
                    messages.append(f"{tower_name} hits {fleet_name} — depleted.")
                else:
                    messages.append(f"{tower_name} hits {fleet_name} — sent to reserve.")
            else:
                messages.append(f"{tower_name} misses {fleet_name}.")
        return messages
