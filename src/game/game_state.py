from src.game.combat import CombatResolver
from src.game.map import Hex, HexGrid
from src.content.loader import load_countries_yaml
from src.game.country import Country, Location

class GameState:
    """
    Represents the state of the game.

    This class encapsulates all aspects of the game state, including the map,
    units, current turn, the countries involved, and event handling. It is
    designed to manage and track game progress, save or load state, and manage
    gameplay elements like units and events.

    :ivar units: A list of game units currently in the game.
    :type units: list
    :ivar map: Represents the game's map structure.
    :type map: Optional[Any]
    :ivar turn: Tracks the current turn number.
    :type turn: int
    :ivar countries: A list of countries participating in the game.
    :type countries: list
    :ivar events: A list of events that occur during the game.
    :type events: list
    """
    def __init__(self):
        self.units = []
        self.map = None  # Will be initialized by load_scenario
        self.turn = 0
        self.countries = []
        self.events = []

    def start_game(self):
        # 1. Get the raw data from the loader
        country_specs = load_countries_yaml("data/countries.yaml")

        # 2. Convert raw data into live game objects
        for cid, spec in country_specs.items():
            new_country = Country(
                id = spec.id,
                capital_id = spec.capital_id,
                # ... pass other spec attributes
            )
            # Convert LocationSpecs to Location objects
            for l_spec in spec.locations:
                new_country.add_location(Location(l_spec.id, l_spec.loc_type, l_spec.coords))

            self.countries[cid] = new_country

    def end_game(self):
        pass

    def save_state(self, filename):
        pass

    def load_state(self, filename):
        pass

    def load_scenario(self, scenario_data, master_map_data):
        """
        Initializes the game state from scenario data.
        """
        map_conf = scenario_data['scenario']['map_settings']

        # 1. Initialize HexGrid with offsets
        # Convert offset_col/row to axial q/r if necessary
        start_hex = Hex.offset_to_axial(map_conf['offset_col'], map_conf['offset_row'])

        self.map = HexGrid(
            width=map_conf['width'],
            height=map_conf['height'],
            offset_q=start_hex.q,
            offset_r=start_hex.r
        )

        # 2. Populate Map Data
        self.map.grid = master_map_data['terrain_map']
        self.map.hexside_data = master_map_data['hexside_map']

        # 3. Setup Countries and Units
        # (This is where you'd loop through scenario_data['setup'] to
        # create countries and place units on the map)
        pass

    def next_turn(self):
        """
        Advances the game to the next turn.
        Resets unit capacities and increments turn counter.
        """
        self.turn += 1

        for unit in self.units:
            # Rule 5: Reset MP to the base allowance defined in units.csv
            unit.movement_points = unit.movement

            # Reset combat and movement flags
            unit.attacked_this_turn = False

            # If you implement Rules for 'exhaustion' or 'depletion',
            # this is where you handle recovery.

        # Optional: Trigger scenario events for the new turn
        self.check_events()

    def check_events(self):
        """Iterates through active events to see if turn-based triggers fire."""
        for event in self.events:
            if event.check_trigger(self):
                event.activate(self)

    def add_unit(self, unit):
        pass

    def get_units_by_country(self, country):
        pass

    def get_units_at(self, hex_coord):
        """
        GameState asks the map's unit_map for the units at this coordinate.
        """
        return self.map.get_units_in_hex(hex_coord.q, hex_coord.r)

    def move_unit(self, unit, target_hex):
        """
        Centralizes the move: updates unit.position AND the spatial map.
        """
        self.map.remove_unit_from_spatial_map(unit)
        unit.position = (target_hex.q, target_hex.r)
        self.map.add_unit_to_spatial_map(unit)

    def resolve_event(self, event):
        pass

    def get_map(self):
        return self.map

    def resolve_combat(self, attackers, hex_position):
        """
        Initiates combat resolution for a specific hex.
        """
        defenders = self.get_units_at(hex_position)
        terrain = self.map.get_terrain(hex_position)
        
        resolver = CombatResolver(attackers, defenders, terrain)
        result = resolver.resolve()
        
        self.apply_combat_result(result)

    def get_units_at(self, position):
        return [u for u in self.units if u.position == position]