# --- Core Wargame Engine ---
# This file contains the foundational, reusable classes for any hex-based wargame.

import collections

# A named tuple to hold cube coordinates for our hexagonal grid.
# Cube coordinates make many hex grid calculations (like distance) much simpler.
# q + r + s must always equal 0.
Hex = collections.namedtuple("Hex", ["q", "r", "s"])

class HexTile:
    """
    Represents a single tile on the map. It contains a Hex coordinate and
    terrain information.
    """
    def __init__(self, hex_coord, terrain_type="Clear"):
        self.hex = hex_coord
        self.terrain_type = terrain_type
        self.units = []  # List of GameUnit objects currently on this tile

        # Terrain-specific properties
        self.movement_cost = self.get_movement_cost()
        self.defense_bonus = self.get_defense_bonus()

    def add_unit(self, unit):
        """Adds a unit to this tile and updates the unit's location."""
        if unit not in self.units:
            self.units.append(unit)
            unit.location = self.hex

    def remove_unit(self, unit):
        """Removes a unit from this tile."""
        if unit in self.units:
            self.units.remove(unit)

    def get_movement_cost(self, unit_type=None):
        """
        Returns the movement cost for this terrain.
        This can be expanded to depend on the unit_type (e.g., tanks in forest).
        """
        terrain_costs = {
            "Clear": 1,
            "Forest": 2,
            "Hill": 2,
            "City": 3,
            "River": float('inf'), # Impassable for now
        }
        return terrain_costs.get(self.terrain_type, 1)

    def get_defense_bonus(self):
        """Returns the defensive bonus for this terrain."""
        terrain_bonuses = {
            "Forest": 2,
            "Hill": 3,
            "City": 4,
        }
        return terrain_bonuses.get(self.terrain_type, 0)

    def __repr__(self):
        return f"Tile({self.hex}, {self.terrain_type})"