from src.content.constants import HL, WS, NEUTRAL
from src.content.specs import CountrySpec, LocationSpec, UnitType


class Location:
    """
    Represents a strategic point on the map.
    Example: Location('solace', 'city', (12, 15), name='Solace')
    Location types:
        - 'city': A fortified city.
        - 'port': A port city.
        - 'fortress': A fortress.
        - 'undercity': An underground city (typically a dwarven fortress).
        - 'temple': The Dark Temple of Takhisis, where draconians are created
    """

    def __init__(self, spec: LocationSpec, country_id: str | None = None):
        self.spec = spec
        self.id = spec.id
        self.country_id = country_id

        # Dynamic State
        self.occupier = NEUTRAL  # 'highlord', 'whitestone', or 'Neutral'
        self.is_capital = spec.is_capital  # Can change (Silvanesti/Qualinesti)

    @property
    def loc_type(self):
        return self.spec.loc_type

    @property
    def coords(self):
        return self.spec.coords

    def get_defense_modifier(self):
        # Access type via spec
        if self.loc_type == UnitType.FORTRESS:
            return -4
        if self.loc_type == UnitType.UNDERCITY:
            return -10
        if self.loc_type in [UnitType.CITY, UnitType.PORT]:
            return -2
        return 0

    def __repr__(self):
        prefix = "Capital " if self.is_capital else ""
        return f"<{prefix}{self.loc_type.title()} {self.id} at {self.coords}>"


class Country:
    def __init__(self, spec: CountrySpec):
        self.spec = spec
        self.id = spec.id

        # Dynamic State
        self.conquerable = True
        self.conquered = False
        self.capital_id = spec.capital_id  # The ID of the location currently serving as capital
        self.allegiance = spec.allegiance  # 'whitestone', 'highlord', or 'neutral'

        # Collections
        self.units = []               # List of Unit objects belonging to this country
        self.locations = {}           # Dict of {loc_id: Location object}

        # Initialize locations from the Spec
        for loc_spec in spec.locations:
            loc = Location(loc_spec, country_id=self.id)
            loc.occupier = self.allegiance
            self.locations[loc_spec.id] = loc

    # --- Property Proxies ---

    @property
    def strength(self):
        return self.spec.strength

    @property
    def alignment(self):
        return self.spec.alignment

    @property
    def color(self):
        return self.spec.color

    @property
    def territories(self):
        # Convert list of lists to set of tuples on the fly or cache it
        # Since territories don't change, we rely on the spec
        return {tuple(t) for t in self.spec.territories}

    @property
    def tags(self):
        return set(self.spec.tags or [])

    @property
    def capital(self):
        """Helper to access the current capital Location object."""
        return self.locations.get(self.capital_id)

    # --- Logic Methods ---

    def is_hex_in_country(self, col, row):
        return (col, row) in self.territories

    def get_name(self, translator):
        return translator.get_country_name(self.id)

    def get_capital_name(self, translator):
        """Returns the translated name of the current capital city."""
        return translator.get_capital_name(self.capital_id)

    def add_location(self, location: Location):
        """Registers a city or fortress and tags it if it's the capital."""
        self.locations[location.id] = location
        if location.id == self.capital_id:
            location.is_capital = True

    def set_capital(self, location_id):
        """Moves the capital status to a different existing location (e.g. Silvanesti)."""
        if location_id in self.locations:
            if self.capital:
                self.capital.is_capital = False
            self.capital_id = location_id
            self.locations[location_id].is_capital = True

    def add_unit(self, unit):
        """Links a unit to this country's management."""
        unit.land = self.id
        unit.allegiance = self.allegiance
        self.units.append(unit)

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    @property
    def total_military_strength(self):
        """Calculates current CR of all active/alive units."""
        return sum(u.combat_rating for u in self.units if u.is_alive())

    def change_allegiance(self, new_allegiance):
        """Flips country and all its units to a new side (Rule DL11 Activation)."""
        self.allegiance = new_allegiance
        for unit in self.units:
            unit.allegiance = new_allegiance

    def is_conquered(self):
        """Returns whether this country has already been conquered (Rule 9)."""
        return self.conquered

    def surrender(self):
        """Rule 9: destroys all units upon total conquest, including reserves."""
        for unit in self.units:
            unit.destroy()

    def __repr__(self):
        return f"<Country {self.id} [{self.allegiance}] - Capital: {self.capital_id}>"
