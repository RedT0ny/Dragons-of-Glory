import random
from typing import Set, Tuple, List, Dict, Optional
from src.game.combat import CombatResolver
from src.content.config import MAP_WIDTH, MAP_HEIGHT
from src.content.constants import DEFAULT_MOVEMENT_POINTS, HL, WS
from src.content.specs import GamePhase, UnitState, UnitRace, LocationSpec, EventType, UnitType
from src.content import loader, factory
from src.game.map import Board, Hex
from src.game.deployment import DeploymentService
from src.game.event_system import EventSystem
from src.game.phase_manager import PhaseManager


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
        self.event_system = EventSystem(self)
        self.phase_manager = PhaseManager(self)
        self.deployment_service = DeploymentService(self)

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
        builder = factory.ScenarioBuilder()
        builder.build(self, scenario_spec)

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
        return self.deployment_service.get_deployment_hexes(allegiance)

    def get_valid_deployment_hexes(self, unit, allow_territory_wide=False) -> List[Tuple[int, int]]:
        return self.deployment_service.get_valid_deployment_hexes(unit, allow_territory_wide=allow_territory_wide)

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
        return self.phase_manager.advance_phase()

    def next_turn(self):
        return self.phase_manager.next_turn()

    def check_events(self):
        return self.event_system.check_events()

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
        return self.event_system.check_event_trigger_conditions(conditions)

    def check_event_requirements_met(self, requirements) -> bool:
        return self.event_system.check_event_requirements_met(requirements)

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
        self.event_system._resolve_add_units(unit_key, allegiance)

    def apply_event_effect(self, spec):
        return self.event_system.apply_event_effect(spec)

    def draw_strategic_event(self, allegiance):
        return self.event_system.draw_strategic_event(allegiance)

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
