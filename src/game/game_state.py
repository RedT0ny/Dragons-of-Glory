from typing import Set, Tuple, List, Dict
from src.game.combat import CombatResolver
from src.content.config import COUNTRIES_DATA, MAP_WIDTH, MAP_HEIGHT, MAP_TERRAIN_DATA, MAP_CONFIG_DATA
from src.content.constants import DEFAULT_MOVEMENT_POINTS, HL, WS
from src.content.specs import GamePhase, UnitState, UnitRace, LocationSpec
from src.content import loader, factory
from src.game.map import Board, Hex


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
        self.prerequisites = set() # Track pre-requirements for events, like artifacts
        self.artifact_pool = {} # ID -> ArtifactSpec blueprint

        # Draconian rules
        self.draconian_ready_at_start = 0

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

    def get_deployment_hexes(self, allegiance: str) -> Set[tuple]:
        """
        Returns a set of (x, y) coordinates where a player can deploy.
        """
        if not self.scenario_spec: return set()

        player_setup = self.scenario_spec.setup.get(allegiance, {})
        area_spec = player_setup.get("deployment_area")

        hexes = set()

        # Case 1: deployment_area is None -> Use all countries assigned to this player
        if area_spec is None:
            countries_to_use = player_setup.get("countries", {}).keys()
            for cid in countries_to_use:
                if cid in self.countries:
                    hexes.update(self.countries[cid].territories)

        # Case 2: deployment_area is a Dictionary (standard format with "countries" key)
        elif isinstance(area_spec, dict):
            countries_to_use = area_spec.get("countries", [])
            for cid in countries_to_use:
                if cid in self.countries:
                    hexes.update(self.countries[cid].territories)

        # Case 3: deployment_area is a List (mixed coords and country IDs)
        elif isinstance(area_spec, list):
            for item in area_spec:
                if isinstance(item, str): # It's a country ID (real or virtual)
                    if item in self.countries:
                        hexes.update(self.countries[item].territories)
                elif isinstance(item, (list, tuple)) and len(item) == 2: # It's a coordinate [col, row]
                    coord = tuple(item)
                    if self.is_hex_in_bounds(coord[0], coord[1]):
                        hexes.add(coord)

        return hexes

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
        if not self.draconian_production_enabled:
            return
        # 1. Check if Dark Temple country exists in this scenario
        # Since it's in countries.yaml, it will be loaded if the scenario references it
        # or if it's a campaign.
        dt_country = self.countries.get("dtemple")

        # If not explicitly in scenario, maybe we need to find it?
        # Actually, if it's not in self.countries, it means it's not part of the play area
        # or active setup, so no production.
        if not dt_country or not dt_country.territories:
            return

        temple_coords = dt_country.territories[0]  # (col, row)
        from src.game.map import Hex
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
                self.phase = GamePhase.STRATEGIC_EVENTS

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
        # Remove from old position in spatial map
        self.map.remove_unit_from_spatial_map(unit)

        # Update Unit's internal state (store as offset col, row for persistence/view)
        offset_coords = target_hex.axial_to_offset()
        unit.position = offset_coords

        # Add to new position in spatial map
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
