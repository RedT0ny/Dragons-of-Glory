from src.game.combat import CombatResolver
from src.game.country import Country, Location
from src.content.config import COUNTRIES_DATA, UNITS_DATA, DEFAULT_MOVEMENT_POINTS, HL, WS
from src.content import loader, factory

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
        self.current_turn_side = HL # Default starting side
        self.countries = []
        self.events = [] # Live Event objects
        self.completed_event_ids = set() # Track for serialization
        self.prerequisites = set() # Track things like "pure_metal"
        self.artifact_pool = {} # ID -> ArtifactSpec blueprint

    def start_game(self):
        # 1. Use the absolute path from config instead of a hardcoded string
        country_specs = loader.load_countries_yaml(COUNTRIES_DATA)

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

    def load_scenario(self, scenario_spec):
        """
        Initializes the game state from scenario data.
        """
        # The factory does all the heavy lifting
        scenario_obj = factory.create_scenario(scenario_spec)

        self.units = scenario_obj.units
        self.countries = scenario_obj.countries

        # 2. Setup the map
        # Create a simple map object that holds width/height
        class SimpleMap:
            def __init__(self, width, height):
                self.width = width
                self.height = height

        self.map = SimpleMap(
            width=getattr(scenario_obj, 'map_width', 65),
            height=getattr(scenario_obj, 'map_height', 53)
        )
        
        # Default to turn 1 if start_turn is missing from the scenario object
        self.turn = getattr(scenario_obj, 'start_turn', 1)
        self.current_turn_side = HL

    def end_phase(self):
        """Swaps the current turn side."""
        if self.current_turn_side == HL:
            self.current_turn_side = WS
        else:
            self.current_turn_side = HL
            self.next_turn()

    def next_turn(self):
        """
        Advances the game to the next turn.
        Resets unit capacities and increments turn counter.
        """
        self.turn += 1

        for unit in self.units:
            # Use the global constant for default movement points
            unit.movement_points = getattr(unit, 'movement', DEFAULT_MOVEMENT_POINTS)

            # Reset combat and movement flags
            unit.attacked_this_turn = False

            # If you implement Rules for 'exhaustion' or 'depletion',
            # this is where you handle recovery.

        # Optional: Trigger scenario events for the new turn
        self.check_events()

    def check_events(self):
        """Iterates through active events to see if turn-based triggers fire."""
        for event in self.events[:]: # Iterate over a copy to allow removal
            if event.check_trigger(self):
                event.activate(self)

                # Logic: If the event has hit its specific limit, remove it from the active pool
                # and track it as completed.
                if event.occurrence_count >= event.spec.max_occurrences:
                    self.completed_event_ids.add(event.id)
                    self.events.remove(event)

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

    def save_game(self, filename: str):
        # Gather unit data using the to_dict method
        unit_data = [u.to_dict() for u in self.units.values()]
        activated = [c.id for c in self.countries.values() if c.is_activated]

        world_state = {
            "turn": self.turn,
            "completed_events": list(self.completed_event_ids),
            "prerequisites": list(self.prerequisites),
            "units": [u.to_dict() for u in self.units]
        }

        loader.save_game_state(
            path=filename,
            scenario_id=self.current_scenario.spec.id,
            turn=self.turn,
            phase=self.phase,
            active_player=self.active_player,
            units=unit_data,
            activated_countries=activated
        )