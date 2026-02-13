import random
from typing import Set, Tuple, List, Dict, Optional
from src.game.combat import CombatResolver, LeaderEscapeRequest
from src.content.config import MAP_WIDTH, MAP_HEIGHT
from src.content.constants import DEFAULT_MOVEMENT_POINTS, HL, WS, NEUTRAL
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

        # Rule tags for country-specific activation logic.
        self.tag_knight_countries = "knight_countries"
        self.tower_country_id = "tower"

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
            deployment_area = setup_data.get("deployment_area")
            country_deployment = bool(setup_data.get("country_deployment", False))

            if isinstance(deployment_area, str) and deployment_area.lower() == "country_based":
                deployment_area = None
                country_deployment = True

            # Create spec from dictionary (handling potential missing keys)
            spec = PlayerSpec(
                allegiance=allegiance,
                deployment_area=deployment_area,
                country_deployment=country_deployment,
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

    def apply_conscription(self, kept_unit, discarded_unit):
        """Apply conscription result: keep one unit, destroy the other."""
        kept_unit.status = UnitState.READY
        discarded_unit.status = UnitState.DESTROYED

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

    def get_country_by_hex(self, col: int, row: int):
        """Returns the Country owning the given offset hex, if any."""
        for country in self.countries.values():
            if (col, row) in country.territories:
                return country
        return None

    def is_country_neutral(self, country_id: str) -> bool:
        country = self.countries.get(country_id)
        return bool(country and country.allegiance == NEUTRAL)

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
            if unit.position[0] is None or unit.position[1] is None:
                start_hex = None
            else:
                start_hex = Hex.offset_to_axial(*unit.position)

            if start_hex is not None:
                # Ensure attribute exists (defensive coding)
                if not hasattr(unit, 'movement_points'):
                    unit.movement_points = unit.movement

                # Calculate path cost using A* to ensure we deduct the optimal cost
                path = self.map.find_shortest_path(unit, start_hex, target_hex)
                if not path and start_hex != target_hex:
                    return

                cost = 0
                current = start_hex
                for next_step in path:
                    step_cost = self.map.get_movement_cost(unit, current, next_step)
                    cost += step_cost
                    current = next_step

                if cost > unit.movement_points:
                    return
                unit.movement_points = max(0, unit.movement_points - cost)

        # 2. Update Position
        # Remove from old position in spatial map
        self.map.remove_unit_from_spatial_map(unit)

        # Update Unit's internal state (store as offset col, row for persistence/view)
        offset_coords = target_hex.axial_to_offset()
        unit.position = offset_coords

        # Add to new position in spatial map
        self.map.add_unit_to_spatial_map(unit)

        if self.phase == GamePhase.MOVEMENT:
            unit.moved_this_turn = True

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

        previous_allegiance = country.allegiance
        country.allegiance = allegiance

        # Update units status to READY
        for u in self.units:
            if u.land == country_id:
                u.status = UnitState.READY
                u.allegiance = allegiance

        self._apply_solamnic_tower_activation(country_id, previous_allegiance)

        print(f"Country {country_id} activated for {allegiance}")

    def is_solamnic_country_for_tower_rule(self, country_id: str) -> bool:
        country = self.countries.get(country_id)
        return bool(
            country
            and country.id != self.tower_country_id
            and self._country_has_tag(country, self.tag_knight_countries)
        )

    def get_ws_solamnic_activation_bonus(self) -> int:
        """+1 WS activation rating per linked Solamnic nation controlled by HL."""
        return sum(
            1
            for country in self._countries_with_tag(self.tag_knight_countries)
            if country.id != self.tower_country_id
            if country.allegiance == HL
        )

    def _apply_solamnic_tower_activation(self, country_id: str, previous_allegiance: str):
        """
        Rule: when the first linked Solamnic nation becomes activated (leaves neutral),
        Tower is activated for WS as well.
        """
        country = self.countries.get(country_id)
        if (
            not country
            or country.id == self.tower_country_id
            or not self._country_has_tag(country, self.tag_knight_countries)
        ):
            return
        if previous_allegiance != NEUTRAL:
            return

        # "First activated" means all other linked nations are still neutral.
        any_other_already_activated = any(
            c.id != country_id and c.allegiance != NEUTRAL
            for c in self._countries_with_tag(self.tag_knight_countries)
            if c.id != self.tower_country_id
        )
        if any_other_already_activated:
            return

        tower = self.countries.get(self.tower_country_id)
        if not tower or tower.allegiance != NEUTRAL:
            return

        tower.allegiance = WS
        for u in self.units:
            if u.land == tower.id:
                u.status = UnitState.READY
                u.allegiance = WS

        print(f"Country {tower.id} activated for whitestone (first Solamnic activation).")

    def _country_has_tag(self, country, tag: str) -> bool:
        if hasattr(country, "has_tag"):
            return country.has_tag(tag)
        return tag in set(getattr(country, "tags", []))

    def _countries_with_tag(self, tag: str):
        return [c for c in self.countries.values() if self._country_has_tag(c, tag)]

    def get_enemy_allegiance(self, allegiance: str) -> Optional[str]:
        if allegiance == HL:
            return WS
        if allegiance == WS:
            return HL
        return None

    def can_use_location_for_deployment(self, country, location, allegiance: str) -> bool:
        """
        Rule 9 deployment ownership:
        - Original owner can deploy only while location is not enemy-occupied.
        - Conqueror can deploy from locations they occupy.
        """
        if allegiance not in (HL, WS):
            return False
        if not location or not location.coords:
            return False

        if location.occupier == allegiance:
            return True
        return country.allegiance == allegiance and location.occupier is None

    def get_solamnic_group_deployment_locations(self, allegiance: str):
        """
        Returns deployable locations in the Solamnic conquest group for the given side.
        Used to allow pooled replacements before the group is fully conquered.
        """
        coords = []
        for country in self._countries_with_tag(self.tag_knight_countries):
            if country.allegiance != allegiance:
                continue
            if country.conquered:
                continue
            for loc in country.locations.values():
                if loc.coords and self.can_use_location_for_deployment(country, loc, allegiance):
                    coords.append(loc.coords)
        return coords

    def _update_location_occupiers(self):
        """
        Rule 9: location conquest status is evaluated at end of combat phase.
        """
        from src.game.map import Hex

        for country in self.countries.values():
            for loc in country.locations.values():
                if not loc.coords:
                    continue

                enemy = self.get_enemy_allegiance(country.allegiance)
                occupier = None
                hex_obj = Hex.offset_to_axial(*loc.coords)

                if enemy:
                    armies = [
                        u for u in self.map.get_units_in_hex(hex_obj.q, hex_obj.r)
                        if u.is_on_map and hasattr(u, "is_army") and u.is_army() and u.allegiance == enemy
                    ]
                    if armies:
                        occupier = enemy

                loc.occupier = occupier
                if hasattr(self.map, "locations"):
                    key = (hex_obj.q, hex_obj.r)
                    if key in self.map.locations:
                        self.map.locations[key]["occupier"] = occupier

    def _is_country_fully_occupied_by_enemy(self, country) -> bool:
        enemy = self.get_enemy_allegiance(country.allegiance)
        if not enemy:
            return False
        if not country.locations:
            return False
        return all(loc.occupier == enemy for loc in country.locations.values())

    def _destroy_country_upon_conquest(self, country):
        """
        Rule 9 effects:
        - Armies, Wings and Leaders are permanently DESTROYED.
        - Fleets remain.
        """
        destroyed_count = 0
        for unit in self.units:
            if unit.land != country.id:
                continue

            is_army = hasattr(unit, "is_army") and unit.is_army()
            is_wing = unit.unit_type == UnitType.WING
            is_leader = hasattr(unit, "is_leader") and unit.is_leader()
            if not (is_army or is_wing or is_leader):
                continue

            if unit.status == UnitState.DESTROYED:
                continue

            unit.destroy()
            self.map.remove_unit_from_spatial_map(unit)
            destroyed_count += 1

        country.conquered = True
        print(f"Country {country.id} conquered. Destroyed units: {destroyed_count}")

    def _apply_standard_country_conquests(self):
        for country in self.countries.values():
            if country.allegiance not in (HL, WS):
                continue
            if country.conquered:
                continue
            if self._country_has_tag(country, self.tag_knight_countries):
                # Solamnic conquest is resolved as a pooled rule below.
                continue
            if self._is_country_fully_occupied_by_enemy(country):
                self._destroy_country_upon_conquest(country)

    def _apply_solamnic_group_conquest(self):
        """
        Solamnic rule:
        WS-controlled countries in this group (including Tower) are conquered only when
        all their locations are occupied by HL.
        """
        group = [c for c in self._countries_with_tag(self.tag_knight_countries) if c.allegiance == WS]
        if not group:
            return

        fully_occupied = all(self._is_country_fully_occupied_by_enemy(c) for c in group)
        if not fully_occupied:
            return

        for country in group:
            if not country.conquered:
                self._destroy_country_upon_conquest(country)

    def resolve_end_of_combat_conquest(self):
        """
        Full Rule 9 pass. Call exactly when leaving COMBAT phase.
        """
        if not self.map:
            return
        self._update_location_occupiers()
        self._apply_standard_country_conquests()
        self._apply_solamnic_group_conquest()

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
        defenders = list(self.get_units_at(hex_position))
        terrain = self.map.get_terrain(hex_position)
        defender_allegiances = {
            u.allegiance for u in defenders
            if u.allegiance not in ("neutral", None)
        }

        # Cumulative pre-combat special retreats for wings/cavalry.
        special_retreat = self._apply_precombat_special_retreat(attackers, defenders, hex_position)
        if special_retreat["applied"]:
            self._cleanup_destroyed_units(defenders)
            defenders = list(self.get_units_at(hex_position))
            if not any(self._is_combat_stack_unit(u) for u in defenders):
                result = special_retreat["result"]
                advance_available = self._can_advance_after_combat(
                    attackers=attackers,
                    target_hex=hex_position,
                    defender_allegiances=defender_allegiances,
                    attacker_had_to_retreat=False,
                )
                print(self._format_combat_log_entry(attackers, defenders, result))
                return {
                    "result": result,
                    "leader_escape_requests": [],
                    "advance_available": advance_available,
                }

        leader_origins = {}
        leader_stack_has_army = {}
        for unit in attackers + defenders:
            if hasattr(unit, "is_leader") and unit.is_leader() and unit.position:
                origin_hex = Hex.offset_to_axial(*unit.position)
                leader_origins[unit] = origin_hex
                units_in_hex = self.map.get_units_in_hex(origin_hex.q, origin_hex.r)
                leader_stack_has_army[unit] = any(
                    u.allegiance == unit.allegiance and self._is_combat_stack_unit(u)
                    for u in units_in_hex
                )

        resolver = CombatResolver(attackers, defenders, terrain, game_state=self)
        result = resolver.resolve()
        print(self._format_combat_log_entry(attackers, defenders, result))
        self._cleanup_destroyed_units(attackers + defenders)
        leader_escape_requests = self._resolve_leader_escapes(leader_origins, leader_stack_has_army)

        attacker_result_code = result.split('/')[0] if '/' in result else result
        attacker_had_to_retreat = 'R' in attacker_result_code
        advance_available = self._can_advance_after_combat(
            attackers=attackers,
            target_hex=hex_position,
            defender_allegiances=defender_allegiances,
            attacker_had_to_retreat=attacker_had_to_retreat,
        )

        return {
            "result": result,
            "leader_escape_requests": leader_escape_requests or [],
            "advance_available": advance_available,
        }

    def _apply_precombat_special_retreat(self, attackers, defenders, target_hex):
        combat_defenders = [
            u for u in defenders
            if u.is_on_map
            and u.position and u.position[0] is not None and u.position[1] is not None
            and self._is_combat_stack_unit(u)
        ]
        if not combat_defenders:
            return {"applied": False, "result": None}

        # These rules do not apply while defending any location.
        if self.map.get_location(target_hex):
            return {"applied": False, "result": None}

        combat_attackers = [
            u for u in attackers
            if u.is_on_map
            and u.position and u.position[0] is not None and u.position[1] is not None
            and self._is_combat_stack_unit(u)
        ]
        if not combat_attackers:
            return {"applied": False, "result": None}

        # No partial retreats: if any non-wing/cavalry combat defender exists (e.g. infantry),
        # entire defending stack remains to fight.
        if any(u.unit_type not in (UnitType.WING, UnitType.CAVALRY) for u in combat_defenders):
            return {"applied": False, "result": None}

        attacker_has_wing = any(u.unit_type == UnitType.WING for u in combat_attackers)
        attacker_has_cavalry = any(u.unit_type == UnitType.CAVALRY for u in combat_attackers)

        wing_rule = not attacker_has_wing
        cavalry_rule = not attacker_has_wing and not attacker_has_cavalry
        if not (wing_rule or cavalry_rule):
            return {"applied": False, "result": None}

        for unit in combat_defenders:
            self._retreat_single_unit(unit)

        # If cavalry rule applies at all, use the more restrictive marker.
        result = "-/SRC" if cavalry_rule else "-/SRW"
        return {"applied": True, "result": result}

    def _retreat_single_unit(self, unit):
        if not unit.position or unit.position[0] is None or unit.position[1] is None:
            return
        status_before = unit.status
        start_hex = Hex.offset_to_axial(*unit.position)
        valid_hexes = self._get_valid_retreat_hexes(unit, start_hex)
        if not valid_hexes:
            unit.eliminate()
            return
        retreat_hex = random.choice(valid_hexes)
        self.move_unit(unit, retreat_hex)
        # Special pre-combat retreat never applies damage/depletion.
        if unit.is_on_map:
            unit.status = status_before

    def _get_valid_retreat_hexes(self, unit, start_hex):
        valid = []
        for neighbor in start_hex.neighbors():
            col, row = neighbor.axial_to_offset()
            if not self.is_hex_in_bounds(col, row):
                continue
            if not self.map.can_unit_land_on_hex(unit, neighbor):
                continue
            if self.map.has_enemy_army(neighbor, unit.allegiance):
                continue
            if not self.map.can_stack_move_to([unit], neighbor):
                continue

            cost = self.map.get_movement_cost(unit, start_hex, neighbor)
            if cost == float('inf') or cost is None:
                continue

            friendly_present = any(
                u.allegiance == unit.allegiance and (u.is_army() or u.unit_type == UnitType.WING)
                for u in self.map.get_units_in_hex(neighbor.q, neighbor.r)
            )
            if not friendly_present and self.map.is_adjacent_to_enemy(neighbor, unit):
                continue

            valid.append(neighbor)
        return valid

    def _can_advance_after_combat(self, attackers, target_hex, defender_allegiances, attacker_had_to_retreat):
        if attacker_had_to_retreat:
            return False
        if not defender_allegiances:
            return False

        target_offset = target_hex.axial_to_offset()
        remaining_defender_combat_units = [
            u for u in self.map.get_units_in_hex(target_hex.q, target_hex.r)
            if u.is_on_map
            and u.position == target_offset
            and u.allegiance in defender_allegiances
            and self._is_combat_stack_unit(u)
        ]
        if remaining_defender_combat_units:
            return False

        for unit in attackers:
            if not unit.is_on_map or not unit.position:
                continue
            if unit.position[0] is None or unit.position[1] is None:
                continue
            if not (unit.is_army() or unit.unit_type == UnitType.WING):
                continue
            if unit.allegiance != self.active_player:
                continue
            from_hex = Hex.offset_to_axial(*unit.position)
            if target_hex not in from_hex.neighbors():
                continue
            if self.map.can_stack_move_to([unit], target_hex):
                return True
        return False

    def advance_after_combat(self, attackers, target_hex):
        candidates = []
        for unit in attackers:
            if not unit.is_on_map or not unit.position:
                continue
            if unit.position[0] is None or unit.position[1] is None:
                continue
            if not (unit.is_army() or unit.unit_type == UnitType.WING):
                continue

            from_hex = Hex.offset_to_axial(*unit.position)
            if target_hex not in from_hex.neighbors():
                continue
            candidates.append(unit)

        if not candidates:
            return []

        remaining_by_source = {}
        no_adjacent_enemy = {}
        for u in candidates:
            src = tuple(u.position)
            remaining_by_source[src] = remaining_by_source.get(src, 0) + 1
            if src not in no_adjacent_enemy:
                src_hex = Hex.offset_to_axial(*src)
                no_adjacent_enemy[src] = not self.map.is_adjacent_to_enemy(src_hex, u)

        moved = []
        groups = [
            [u for u in candidates if u.unit_type == UnitType.WING],
            [u for u in candidates if u.unit_type == UnitType.CAVALRY],
            [u for u in candidates if u.is_army() and u.unit_type != UnitType.CAVALRY],
        ]

        for group in groups:
            pool = list(group)
            while pool:
                legal = [u for u in pool if self.map.can_stack_move_to([u], target_hex)]
                if not legal:
                    break

                random.shuffle(legal)
                legal.sort(key=lambda u: self._advance_priority_key(u, remaining_by_source, no_adjacent_enemy))
                chosen = legal[0]
                source_before_move = tuple(chosen.position)
                self.move_unit(chosen, target_hex)
                moved.append(chosen)

                if source_before_move in remaining_by_source and remaining_by_source[source_before_move] > 0:
                    remaining_by_source[source_before_move] -= 1

                pool.remove(chosen)

        return moved

    def _advance_priority_key(self, unit, remaining_by_source, no_adjacent_enemy):
        src = tuple(unit.position)
        source_has_no_adjacent_enemy = no_adjacent_enemy.get(src, False)
        leaves_source_empty = remaining_by_source.get(src, 0) <= 1
        return (
            0 if source_has_no_adjacent_enemy else 1,
            1 if leaves_source_empty else 0,
        )

    def _resolve_leader_escapes(self, leader_origins, leader_stack_has_army):
        requests = []
        leaders_to_cleanup = []

        for leader, origin_hex in leader_origins.items():
            if not leader_stack_has_army.get(leader):
                continue
            if not leader.is_on_map or not leader.position:
                continue

            units_in_hex = self.map.get_units_in_hex(origin_hex.q, origin_hex.r)
            has_allied_army = any(
                u.allegiance == leader.allegiance and self._is_combat_stack_unit(u)
                for u in units_in_hex
            )
            if has_allied_army:
                continue

            roll = random.randint(1, 6)
            if roll <= 3:
                leader.destroy()
                leaders_to_cleanup.append(leader)
                print(f"Leader {leader.id} eliminated after battle (roll {roll}).")
                continue

            options = self._get_nearest_friendly_combat_stacks(leader, origin_hex)
            if not options:
                leader.destroy()
                leaders_to_cleanup.append(leader)
                print(f"Leader {leader.id} eliminated (no friendly stacks to escape).")
                continue

            print(f"Leader {leader.id} escapes (roll {roll}).")
            requests.append(LeaderEscapeRequest(leader=leader, options=options))

        if leaders_to_cleanup:
            self._cleanup_destroyed_units(leaders_to_cleanup)

        return requests

    def _get_nearest_friendly_combat_stacks(self, leader, origin_hex):
        candidates = []
        for (q, r), units in self.map.unit_map.items():
            if not units:
                continue
            if not any(
                u.allegiance == leader.allegiance
                and u.is_on_map
                and self._is_combat_stack_unit(u)
                for u in units
            ):
                continue
            candidates.append(Hex(q, r))

        if not candidates:
            return []

        min_distance = min(origin_hex.distance_to(h) for h in candidates)
        return [h for h in candidates if origin_hex.distance_to(h) == min_distance]

    def _is_combat_stack_unit(self, unit):
        return bool(
            (hasattr(unit, "is_army") and unit.is_army())
            or unit.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY, UnitType.WING)
        )

    def _format_combat_log_entry(self, attackers, defenders, result):
        attacker_names = ", ".join(self._format_unit_for_log(u) for u in attackers)
        defender_names = ", ".join(self._format_unit_for_log(u) for u in defenders)
        return f"Combat result {result}: Attackers [{attacker_names}] vs Defenders [{defender_names}]"

    def _format_unit_for_log(self, unit):
        ordinal = getattr(unit, "ordinal", None)
        if ordinal is None:
            return str(unit.id)
        return f"{unit.id}#{ordinal}"

    def clear_leader_tactical_overrides(self):
        for unit in self.units:
            if hasattr(unit, "is_leader") and unit.is_leader():
                if hasattr(unit, "_tactical_rating_override"):
                    unit._tactical_rating_override = None

    def get_map(self):
        return self.map

    def _cleanup_destroyed_units(self, units):
        for unit in units:
            if not unit.is_on_map or not unit.position or unit.position[0] is None or unit.position[1] is None:
                self.map.remove_unit_from_spatial_map(unit)

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
