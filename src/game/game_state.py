import random
from typing import Set, Tuple, List, Dict, Optional
from src.game.combat import CombatResolver
from src.content.config import COUNTRIES_DATA, MAP_WIDTH, MAP_HEIGHT, MAP_TERRAIN_DATA, MAP_CONFIG_DATA, EVENTS_DATA, ARTIFACTS_DATA
from src.content.constants import DEFAULT_MOVEMENT_POINTS, HL, WS
from src.content.specs import GamePhase, UnitState, UnitRace, LocationSpec, EventType, UnitType
from src.content import loader, factory
from src.game.map import Board, Hex
from src.game.event import Event, Asset, check_requirements


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
        self.map: Board = None  # Will be initialized by load_scenario
        self.turn = 0
        self.scenario_spec = None

        # Battle Turn State
        self.phase = GamePhase.REPLACEMENTS
        self.active_player = HL        # Who is currently acting (Default highlord).
        self.initiative_winner = None  # Who won initiative this turn
        self.second_player_has_acted = False # Track if we are in Step 7

        # Game State
        self.countries = {}
        self.events = [] # Live Event objects
        self.completed_event_ids = set() # Track for serialization
        self.artifact_pool = {} # ID -> ArtifactSpec blueprint (Catalog)
        self.players = {} # Dict[str, Player]
        self.strategic_event_pool = [] # Pool of available strategic events

        # Draconian rules
        self.draconian_ready_at_start = 0

    @property
    def current_player(self):
        """Returns the Player object for the active_player allegiance."""
        return self.players.get(self.active_player)

    def get_player(self, allegiance: str):
        return self.players.get(allegiance)

    def end_game(self):
        pass

    def save_state(self, filename: str):
        # Gather unit data using the to_dict method
        unit_data = [u.to_dict() for u in self.units.values()]
        activated = [c.id for c in self.countries.values() if c.is_activated]

        loader.save_game_state(
            path=filename,
            scenario_id=self.current_scenario.spec.id,
            turn=self.turn,
            phase=self.phase,
            active_player=self.active_player,
            units=unit_data,
            activated_countries=activated
        )

    def load_state(self, filename):
        pass

    def load_scenario(self, scenario_spec):
        """
        Initializes the game state from scenario data.
        """
        self.scenario_spec = scenario_spec

        # Setup live objects via Factory
        self.units, self.countries = factory.create_scenario_items(scenario_spec)

        # Apply Draconian scenario rules (ready count, production flag)
        self._apply_draconian_setup()

        # Load Artifacts Catalog
        self.artifact_pool = loader.load_artifacts_yaml(ARTIFACTS_DATA)

        # Setup the map
        bounds = self.get_map_bounds()
        width, height = self.get_map_dimensions()
        offset_col = bounds["x_range"][0]
        offset_row = bounds["y_range"][0]

        if self.scenario_spec and self.scenario_spec.map_subset:
            self._apply_map_subset_offsets(offset_col, offset_row, width, height)

        # Initialize the actual HexGrid model
        self.map = Board(width, height, offset_col=offset_col, offset_row=offset_row)

        # Populate Terrain
        terrain_data = loader.load_terrain_csv(MAP_TERRAIN_DATA)
        self.map.populate_terrain(terrain_data)

        # Populate Hexsides (Rivers, Mountains)
        map_config = loader.load_map_config(MAP_CONFIG_DATA)
        self.map.populate_hexsides(map_config.hexsides)

        # Populate Locations (Special + Country)
        special_locations = map_config.special_locations
        if self.scenario_spec and self.scenario_spec.map_subset:
            special_locations = self._adjust_special_locations(
                special_locations, offset_col, offset_row
            )
        self.map.populate_locations(special_locations, self.countries)

        # Initialize Players (after map offsets are applied to the spec)
        self._initialize_players()

        # Load Strategic Events
        event_specs = loader.resolve_scenario_events(self.scenario_spec, EVENTS_DATA)
        self.strategic_event_pool = []
        for s in event_specs:
            # We pass generic lambdas that delegate back to GameState logic
            evt = Event(s,
                        trigger_func=lambda gs, s=s: gs.check_event_trigger_conditions(s.trigger_conditions),
                        effect_func=lambda gs, s=s: gs.apply_event_effect(s))
            self.strategic_event_pool.append(evt)

        # Register existing units on the map if they have positions
        for unit in self.units:
            if unit.position and unit.is_on_map:
                self.map.add_unit_to_spatial_map(unit)

        # Register existing units on the map if they have positions
        for unit in self.units:
            if unit.position and unit.is_on_map:
                self.map.add_unit_to_spatial_map(unit)

        # 5. Default to turn 1 if start_turn is missing from the scenario object
        self.turn = getattr(scenario_spec, 'start_turn', 1)

        # Determine initiative for Deployment
        init_str = getattr(scenario_spec, 'initiative_start', 'highlord').lower()

        # Start with Deployment Phase
        self.phase = GamePhase.DEPLOYMENT

        # The player WITHOUT initiative deploys first
        if init_str == WS:
            self.initiative_winner = WS
            self.active_player = HL
        else:
            self.initiative_winner = HL
            self.active_player = WS

    def get_map_bounds(self) -> Dict[str, List[int]]:
        """Returns the subset range or full map defaults."""
        if self.scenario_spec and self.scenario_spec.map_subset:
            return self.scenario_spec.map_subset

        return {
            "x_range": [0, MAP_WIDTH - 1],
            "y_range": [0, MAP_HEIGHT - 1]
        }

    def get_map_dimensions(self) -> Tuple[int, int]:
        """Returns (width, height) based on map subset or default config."""
        bounds = self.get_map_bounds()
        width = bounds['x_range'][1] - bounds['x_range'][0] + 1
        height = bounds['y_range'][1] - bounds['y_range'][0] + 1
        return width, height

    def is_hex_in_bounds(self, q: int, r: int) -> bool:
        """Helper to check if a specific offset coordinate is within this scenario's map."""
        bounds = self.get_map_bounds()
        return (bounds["x_range"][0] <= q <= bounds["x_range"][1] and
                bounds["y_range"][0] <= r <= bounds["y_range"][1])

    def _initialize_players(self):
        """Creates Player objects based on scenario setup."""
        from src.game.player import Player
        from src.content.specs import PlayerSpec

        self.players = {}
        for allegiance in [HL, WS]:
            setup_data = self.scenario_spec.setup.get(allegiance, {})

            # Create spec from dictionary (handling potential missing keys)
            spec = PlayerSpec(
                allegiance=allegiance,
                deployment_area=setup_data.get("deployment_area"),
                setup_countries=setup_data.get("countries", {}),
                explicit_units=setup_data.get("explicit_units", []),
                victory_conditions=setup_data.get("victory_conditions", {}) or self.scenario_spec.victory_conditions.get(allegiance, {}),
                pre_req=setup_data.get("pre_req", []),
                artifacts=setup_data.get("artifacts", []),
                is_ai=False # Default to False, Controller will override
            )

            player = Player(spec)
            self.players[allegiance] = player

            # Assign controlled countries based on 'countries' key in setup
            # If not specified, maybe fall back? Scenario usually specifies active countries.
            country_ids = spec.setup_countries.keys()
            for cid in country_ids:
                if cid in self.countries:
                    player.add_country(self.countries[cid])

    def get_deployment_hexes(self, allegiance: str) -> Set[tuple]:
        """
        Returns a set of (x, y) coordinates where a player can deploy.
        Delegates to the Player object.
        """
        if allegiance not in self.players:
            return set()

        return self.players[allegiance].get_deployment_hexes(self.countries, self.is_hex_in_bounds)

    def get_valid_deployment_hexes(self, unit, allow_territory_wide=False) -> List[Tuple[int, int]]:
        """
        Calculates valid deployment coordinates for a specific unit,
        applying Phase rules, Unit Type restrictions (Fleets), and Terrain checks.
        """
        candidates = []

        # 1. Gather Candidates based on Phase
        if self.phase == GamePhase.DEPLOYMENT:
            # Scenario specific areas
            candidates = list(self.get_deployment_hexes(unit.allegiance))
        else:
            # Replacements / Activation
            country = self.countries.get(unit.land)
            if country:
                if allow_territory_wide:
                    candidates = list(country.territories)
                else:
                    # Cities or Fortresses
                    for loc in country.locations.values():
                        if loc.coords:
                            candidates.append(loc.coords)
            else:
                # Handle stateless units (units without land) during REPLACEMENTS phase
                # These units should be deployable in any friendly location
                if self.phase == GamePhase.REPLACEMENTS and unit.allegiance == self.active_player:
                    # Find all friendly locations (fortresses, cities, ports, undercities, etc.)
                    for country_id, country_obj in self.countries.items():
                        if country_obj.allegiance == unit.allegiance:
                            # Add all locations from friendly countries
                            for loc in country_obj.locations.values():
                                if loc.coords:
                                    candidates.append(loc.coords)

        # 2. Filter based on Unit Type & Terrain
        valid_hexes = []
        country = self.countries.get(unit.land)

        for col, row in candidates:
            hex_obj = Hex.offset_to_axial(col, row)

            if unit.unit_type == UnitType.FLEET:
                # Rule: Coastal and Port (Deployment) or Port (Replacements)
                # Note: We pass self.phase to map validation logic
                if country and self.map.is_valid_fleet_deployment(hex_obj, country, self.phase):
                    if self.map.can_stack_move_to([unit], hex_obj):
                        valid_hexes.append((col, row))
            else:
                # Ground Units: Cannot deploy into Ocean
                # (Unless specific amphibious rules exist, but generally no)
                if self.map.can_unit_land_on_hex(unit, hex_obj):
                    if self.map.can_stack_move_to([unit], hex_obj):
                        valid_hexes.append((col, row))

        return valid_hexes

    def _apply_map_subset_offsets(self, offset_col: int, offset_row: int, width: int, height: int):
        """Normalize scenario and country coordinates to local (subset) space."""
        # Convert country territories and locations to local coords
        for country in self.countries.values():
            country.spec.territories = [
                (col - offset_col, row - offset_row)
                for col, row in country.spec.territories
            ]
            for loc_spec in country.spec.locations:
                if loc_spec.coords:
                    col, row = loc_spec.coords
                    loc_spec.coords = (col - offset_col, row - offset_row)

        # Convert deployment areas that use explicit coordinates
        for allegiance in [HL, WS]:
            setup = self.scenario_spec.setup.get(allegiance, {})
            area_spec = setup.get("deployment_area")

            if isinstance(area_spec, list):
                new_area = []
                for item in area_spec:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        new_area.append((item[0] - offset_col, item[1] - offset_row))
                    else:
                        new_area.append(item)
                setup["deployment_area"] = new_area
            elif isinstance(area_spec, dict):
                for key in ["coords", "hexes"]:
                    coords_list = area_spec.get(key)
                    if isinstance(coords_list, list):
                        new_coords = []
                        for item in coords_list:
                            if isinstance(item, (list, tuple)) and len(item) == 2:
                                new_coords.append((item[0] - offset_col, item[1] - offset_row))
                            else:
                                new_coords.append(item)
                        area_spec[key] = new_coords

        # Normalize bounds to local coordinate space
        self.scenario_spec.map_subset = {
            "x_range": [0, width - 1],
            "y_range": [0, height - 1]
        }

    def _adjust_special_locations(self, special_locations, offset_col: int, offset_row: int):
        """Shift master-map special locations into local subset coordinates."""
        adjusted = []
        for loc in special_locations:
            if not loc.coords:
                continue
            col, row = loc.coords
            adjusted.append(LocationSpec(
                id=loc.id,
                loc_type=loc.loc_type,
                coords=(col - offset_col, row - offset_row),
                is_capital=loc.is_capital
            ))
        return adjusted

    def set_initiative(self, winner):
        """Called by Controller after Step 4 dice roll."""
        self.initiative_winner = winner
        self.active_player = winner # Winner goes first

    def _apply_draconian_setup(self):
        """Reads dtemple config from scenario YAML and applies READY / production flags."""
        hl_setup = self.scenario_spec.setup.get("highlord", {})
        dtemple_cfg = hl_setup.get("countries", {}).get("dtemple")

        if not isinstance(dtemple_cfg, dict):
            return

        # Ready count (defaults to 0)
        self.draconian_ready_at_start = int(dtemple_cfg.get("ready", 0))

        # Normalize all draconians first
        draconians = [u for u in self.units if u.land == "dtemple" and u.race == UnitRace.DRACONIAN]
        for unit in draconians:
            unit.status = UnitState.INACTIVE

        # Then mark first N as READY
        for i, unit in enumerate(draconians):
            if i < self.draconian_ready_at_start:
                unit.ready()

    def process_draconian_production(self):
        """
        Rule: At replacement step, HL manufactures 1 Draconian at the Dark Temple
        if the hex is not enemy controlled.
        """
        # 1. Check if Dark Temple country exists in this scenario
        # Since it's in countries.yaml, it will be loaded if the scenario references it
        # or if it's a campaign.
        dt_country = self.countries.get("dtemple")

        # If not explicitly in scenario, maybe we need to find it?
        # Actually, if it's not in self.countries, it means it's not part of the play area
        # or active setup, so no production.
        if not dt_country:
            return

        temple_coords = dt_country.capital.coords  # (col, row)
        temple_axial = Hex.offset_to_axial(*temple_coords)

        # 2. Check Ownership/Occupation (Rule: If captured by WS, no production)
        # "Captured" in this game usually means occupying the hex.
        if self.map.has_enemy_army(temple_axial, HL):
            # Temple is besieged or captured
            return

        # 3. Find one INACTIVE or RESERVE Draconian linked to Dark Temple
        # Since units.csv likely assigns them to 'dtemple', we look for that.
        candidate = next((u for u in self.units
                          if u.land == "dtemple" and u.status in [UnitState.INACTIVE, UnitState.RESERVE]), None)

        if candidate:
            candidate.ready()  # Move to READY so it appears in the dialog
            print(f"Dark Temple produced: {candidate.id}")

    def resolve_maelstrom_entry(self, unit, maelstrom_hex=None):
        """
        Executes the Maelstrom effect table (1d10).
        Called when entering Maelstrom or at start of turn if trapped.

        Returns a dict with result info for the UI/Controller to act on:
        {
            "roll": int,
            "effect": "sink" | "stay" | "emerge",
            "chooser": "player" | "opponent" | None,
            "options": [Hex, ...] (for emerge)
        }
        """
        roll = random.randint(1, 10)
        result = {"roll": roll, "unit": unit}

        # 1. Sink
        if roll == 1:
            result["effect"] = "sink"
            unit.destroy()
            print(f"Maelstrom Effect (Roll {roll}): Ship {unit.id} destroyed!")

        # 2-5. Stay
        elif 2 <= roll <= 5:
            result["effect"] = "stay"
            # End movement immediately
            unit.movement_points = 0
            # Ensure it is in the maelstrom hex (if passed for placement)
            if maelstrom_hex:
                self.move_unit(unit, maelstrom_hex)
            print(f"Maelstrom Effect (Roll {roll}): Ship {unit.id} trapped for the turn.")

        # 6-8. Opponent Chooses Exit
        elif 6 <= roll <= 8:
            result["effect"] = "emerge"
            result["chooser"] = "opponent"

            # Identify current location to find neighbors
            current_hex = maelstrom_hex if maelstrom_hex else Hex.offset_to_axial(*unit.position)
            result["options"] = self.map.get_maelstrom_exits(current_hex)
            print(f"Maelstrom Effect (Roll {roll}): Opponent chooses exit for {unit.id}.")

        # 9-10. Player Chooses Exit
        else: # 9, 10
            result["effect"] = "emerge"
            result["chooser"] = "player"

            current_hex = maelstrom_hex if maelstrom_hex else Hex.offset_to_axial(*unit.position)
            result["options"] = self.map.get_maelstrom_exits(current_hex)
            print(f"Maelstrom Effect (Roll {roll}): Player chooses exit for {unit.id}.")

        return result

    def process_maelstrom_start_turn(self):
        """
        Checks for ships trapped in the Maelstrom at the start of Step 5.
        """
        # Find all fleets currently located in Maelstrom hexes
        trapped_ships = []
        for unit in self.units:
            if unit.is_on_map and unit.unit_type == UnitType.FLEET:
                if unit.position:
                    hex_obj = Hex.offset_to_axial(*unit.position)
                    if self.map.is_maelstrom(hex_obj):
                        trapped_ships.append((unit, hex_obj))

        # Roll for each ship belonging to the active player
        for unit, hex_obj in trapped_ships:
            if unit.allegiance == self.active_player:
                print(f"Processing Maelstrom check for trapped ship: {unit.id}")
                self.resolve_maelstrom_entry(unit, hex_obj)
                # Note: The 'emerge' result requires handling by the Controller/UI
                # to prompt selection from result['options'].

    def advance_phase(self):
        """
        The State Machine: Determines the next phase based on current state.
        This ensures the strict order of the Battle Turn.
        """
        if self.phase == GamePhase.DEPLOYMENT:
            # If currently the non-initiative player, switch to initiative player
            # If currently the initiative player, deployment is done AND it counts as their Replacements.

            if self.active_player != self.initiative_winner:
                self.active_player = self.initiative_winner
                # Phase remains DEPLOYMENT for the second player
            else:
                # Initiative winner finished deployment.
                # Proceed directly to movement (Skipping activation, events and initiative phases for this first turn)
                self.phase = GamePhase.MOVEMENT

        elif self.phase == GamePhase.REPLACEMENTS:
            # Logic: The player that lost initiative roll goes first in replacements (Handled in nex_turn).
            # First check if active_player is HL, to process draconian production
            if self.active_player == HL:
                self.process_draconian_production()
            # Now check if we are in the first or second player replacement round
            if self.active_player != self.initiative_winner:
                # That means it's the first player replacing
                self.active_player = self.initiative_winner
                # Phase remains REPLACEMENTS for the second player
            else:
                self.phase = GamePhase.STRATEGIC_EVENTS

        elif self.phase == GamePhase.STRATEGIC_EVENTS:
            if self.active_player == self.initiative_winner:
                # That means it's the event for the first player
                self.active_player = WS if self.initiative_winner == HL else HL
                # Phase remains STRATEGIC_EVENTS for the second player
                # Note: since this phase is fully automatic, maybe this is not required
                # and can be handled directly in the controller.
            else:
                self.phase = GamePhase.ACTIVATION

        elif self.phase == GamePhase.ACTIVATION:
            if self.active_player != self.initiative_winner:
                # That means it's the event for the first player
                self.active_player = self.initiative_winner
                # Phase remains ACTIVATION for the second player
            else:
                self.phase = GamePhase.INITIATIVE

        elif self.phase == GamePhase.INITIATIVE:
            # Controller must have set_initiative() before calling this
            self.phase = GamePhase.MOVEMENT
            self.second_player_has_acted = False

        elif self.phase == GamePhase.MOVEMENT:
            self.phase = GamePhase.COMBAT

        elif self.phase == GamePhase.COMBAT:
            if not self.second_player_has_acted:
                # End of First Player's turn (Step 6 done).
                # Start Second Player's turn (Step 7).
                self.phase = GamePhase.MOVEMENT
                self.active_player = WS if self.active_player == HL else HL
                self.second_player_has_acted = True
            else:
                # End of Second Player's turn. Turn over (Step 8).
                self.next_turn()

    def next_turn(self):
        """Advances the game to the next turn (Step 8)."""
        self.turn += 1
        self.phase = GamePhase.REPLACEMENTS
        # Change active_player to the one that lost initiative roll, so they go first in replacements
        self.active_player = WS if self.initiative_winner == HL  else HL

        # Reset unit flags
        for unit in self.units:
            unit.movement_points = getattr(unit, 'movement', 0) # Reset MPs
            unit.attacked_this_turn = False
            # Handle status recovery/exhaustion here if needed

        # Check events
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
        target_hex: Hex object (axial)
        """
        # Prevent moving units that are transported aboard a carrier
        if getattr(unit, 'transport_host', None) is not None:
            # Transported armies cannot move on their own while aboard
            print(f"Unit {unit.id} is transported aboard {unit.transport_host.id} and cannot move independently.")
            return

        # 1. Deduct Movement Points (Only in Movement Phase)
        # We check if unit is already on map to avoid cost calculation for deployment/teleport
        if self.phase == GamePhase.MOVEMENT and unit.position:
            start_hex = Hex.offset_to_axial(*unit.position)

            # Ensure attribute exists (defensive coding)
            if not hasattr(unit, 'movement_points'):
                unit.movement_points = unit.movement

            # Calculate path cost using A* to ensure we deduct the optimal cost
            path = self.map.find_shortest_path(unit, start_hex, target_hex)

            cost = 0
            current = start_hex
            for next_step in path:
                step_cost = self.map.get_movement_cost(unit, current, next_step)
                cost += step_cost
                current = next_step

            unit.movement_points = max(0, unit.movement_points - cost)

        # 2. Update Position
        # Remove from old position in spatial map
        self.map.remove_unit_from_spatial_map(unit)

        # Update Unit's internal state (store as offset col, row for persistence/view)
        offset_coords = target_hex.axial_to_offset()
        unit.position = offset_coords

        # Add to new position in spatial map
        self.map.add_unit_to_spatial_map(unit)

        # If this unit is a carrier (Fleet/Wing/Citadel) move its passengers implicitly
        passengers = getattr(unit, 'passengers', None)
        if passengers:
            for p in passengers:
                # Update passenger state to remain transported; do NOT add them to spatial map
                p.position = unit.position
                p.is_transported = True
                p.transport_host = unit

    def check_event_trigger_conditions(self, conditions) -> bool:
        """Checks if a list of trigger conditions is met."""
        if not conditions:
            return False

        # Example condition format: "turn: 5" or "always_true" or dict
        for cond in conditions:
            if isinstance(cond, str):
                if cond == "always_true":
                    return True
                # Parse simple strings if needed
            elif isinstance(cond, dict):
                if "turn" in cond and self.turn == cond["turn"]:
                    return True
                # Add more conditions as needed (e.g. "unit_at")

        return False

    def check_event_requirements_met(self, requirements) -> bool:
        """Checks if event prerequisites are met."""
        if not requirements:
            return True

        current_player_obj = self.current_player
        for req in requirements:
            # Reusing the shared check_requirements from event.py
            if not check_requirements(req, current_player_obj, self):
                return False
        return True

    def activate_country(self, country_id: str, allegiance: str):
        """Activates a country for the given allegiance and readies its units."""
        country = self.countries.get(country_id)
        if not country:
            print(f"Warning: Country {country_id} not found for activation.")
            return

        country.allegiance = allegiance

        # Update units status to READY
        from src.content.specs import UnitState
        for u in self.units:
            if u.land == country_id:
                u.status = UnitState.READY
                u.allegiance = allegiance

        print(f"Country {country_id} activated for {allegiance}")

    def _resolve_add_units(self, unit_key: str, allegiance: str):
        """Resolves generic add_units keys to specific units and readies them."""
        candidates = []

        # 1. Wizards
        if unit_key == "wizard":
            candidates = [u for u in self.units
                          if u.unit_type == UnitType.WIZARD and u.allegiance == allegiance]

        # 2. Flying Citadel
        elif unit_key == "citadel":
            # Assuming UnitType.CITADEL exists, otherwise checking string representation
            candidates = [u for u in self.units
                          if (u.unit_type == UnitType.CITADEL if hasattr(UnitType, 'CITADEL') else str(u.unit_type).lower() == 'citadel')
                          and u.allegiance == allegiance]

        # 3. Golden General (Laurana)
        elif unit_key == "golden_general":
            candidates = [u for u in self.units if u.id == "laurana"]

        # 4. Good Dragons
        elif unit_key == "good_dragons":
            candidates = [u for u in self.units
                          if u.unit_type == UnitType.WING and u.allegiance == "whitestone"]

        # Fallback: Try to find by direct ID match
        if not candidates:
            candidates = [u for u in self.units if u.id == unit_key]

        if not candidates:
            print(f"Warning: No units found for add_units key '{unit_key}'")

        for u in candidates:
            # Move to READY so they appear in deployment
            u.status = UnitState.READY
            u.allegiance = allegiance
            print(f"Unit {u.id} added/ready for {allegiance}")

    def apply_event_effect(self, spec):
        """Applies the effects of an event."""
        if not spec.effects:
            return

        player = self.current_player
        effects = spec.effects

        # 1. Alliance: Activates country and readies units
        if "alliance" in effects:
            country_id = effects["alliance"]
            self.activate_country(country_id, player.allegiance)

        # 2. Add Units: Adds specific units to the pool (READY state)
        if "add_units" in effects:
            unit_key = effects["add_units"]
            self._resolve_add_units(unit_key, player.allegiance)

        # 3. Grant Asset: Processed last
        if "grant_asset" in effects:
            asset_id = effects["grant_asset"]
            # Delegate to Player class to ensure consistent asset creation and storage
            player.grant_asset(asset_id, self)

        # Other effects...

    def draw_strategic_event(self, allegiance):
        """
        Draws an event for the given allegiance based on triggers and probability.
        """
        # 1. Check for Auto-Triggers (Highest priority)
        candidates = []
        for event in self.strategic_event_pool:
            if event.id in self.completed_event_ids: continue
            if event.occurrence_count >= event.spec.max_occurrences: continue

            # Allegiance check: Must match player OR be neutral (None)
            # "Each player can only draw either an event of their allegiance or an event without allegiance"
            if event.spec.allegiance and event.spec.allegiance != allegiance: continue

            candidates.append(event)

        # Check triggers
        for event in candidates:
            if event.spec.trigger_conditions:
                if self.check_event_trigger_conditions(event.spec.trigger_conditions):
                    return event

        # 2. Check "Possible" Events (Random Draw)
        possible_events = []
        weights = []

        for event in candidates:
            # Skip if it has triggers (handled above, don't draw randomly if trigger didn't fire)
            if event.spec.trigger_conditions:
                continue

            # Pre-requirements
            if not self.check_event_requirements_met(event.spec.requirements):
                continue

            # Turn check and Probability Weight Calculation
            if event.spec.turn is None:
                diff = 0
            else:
                if self.turn < event.spec.turn:
                    continue
                diff = self.turn - event.spec.turn

            # Formula: chance reduces as diff increases
            # Base prob * (1 / (1 + 0.5 * diff)) - tunable decay
            decay = 1.0 / (1.0 + 0.5 * diff)

            # Use spec.probability (default 1.0)
            weight = getattr(event.spec, 'probability', 1.0) * decay

            possible_events.append(event)
            weights.append(weight)

        if not possible_events:
            return None

        # Draw one
        chosen = random.choices(possible_events, weights=weights, k=1)[0]
        return chosen

    def resolve_event(self, event):
        pass

    def resolve_combat(self, attackers, hex_position):
        """
        Initiates combat resolution for a specific hex.
        """
        defenders = self.get_units_at(hex_position)
        # Need to convert hex_position (axial) to offset for get_terrain if it expects offset?
        # Looking at game_state code, map.get_terrain usually takes axial object or handles conversion.
        # Assuming hex_position is the Axial Hex object passed from controller.

        terrain = self.map.get_terrain(hex_position)

        resolver = CombatResolver(attackers, defenders, terrain)
        result = resolver.resolve()

    def get_map(self):
        return self.map

    def board_unit(self, carrier, unit):
        """Boards `unit` onto `carrier` if allowed.
        Removes the unit from the spatial map, marks it transported and records transport_host.
        Returns True on success, False otherwise.
        """
        if not carrier.can_carry(unit):
            return False

        # Must be co-located
        if not carrier.position or not unit.position or carrier.position != unit.position:
            return False

        # Remove unit from spatial map so it is not considered on the hex while aboard
        self.map.remove_unit_from_spatial_map(unit)
        carrier.load_unit(unit)
        unit.position = carrier.position
        unit.is_transported = True
        unit.transport_host = carrier
        return True

    def unboard_unit(self, unit, target_hex=None):
        """Unboards `unit` from its transport_host into target_hex (axial Hex) or the carrier's hex if None.
        Validates stacking limits using Board.can_stack_move_to. Returns True on success.
        """
        carrier = getattr(unit, 'transport_host', None)
        if not carrier:
            return False

        # Determine destination axial hex
        dest_hex = target_hex
        if dest_hex is None and carrier.position:
            # Use carrier's current axial position
            dest_hex = Hex.offset_to_axial(*carrier.position)

        if dest_hex is None:
            return False

        # Validate stacking limits
        moving_units = [unit]
        if not self.map.can_stack_move_to(moving_units, dest_hex):
            return False

        # Perform unboard: remove from carrier.passengers, clear transport flags, add to spatial map
        if unit in carrier.passengers:
            carrier.passengers.remove(unit)
        unit.transport_host = None
        unit.is_transported = False
        # Place unit into dest offset coords
        offset_coords = dest_hex.axial_to_offset()
        unit.position = offset_coords
        self.map.add_unit_to_spatial_map(unit)
        return True
