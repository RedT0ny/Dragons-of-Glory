import random
import os
from collections import defaultdict
from pathlib import Path
from typing import Set, Tuple, List, Dict, Optional
from src.game.combat import (
    CombatResolver,
    DragonDuelResolver,
    LeaderEscapeRequest,
    NavalCombatResolver,
    apply_dragon_orb_bonus,
    apply_gnome_tech_bonus,
)
from src.content.config import MAP_WIDTH, MAP_HEIGHT, SCENARIOS_DIR
from src.content.constants import DEFAULT_MOVEMENT_POINTS, HL, WS, NEUTRAL
from src.content.specs import GamePhase, UnitState, UnitRace, LocationSpec, EventType, UnitType
from src.content import loader, factory
from src.game.map import Board, Hex
from src.game.deployment import DeploymentService
from src.game.event_system import EventSystem
from src.game.movement import evaluate_unit_move, effective_movement_points
from src.game.phase_manager import PhaseManager
from src.game.victory import VictoryConditionEvaluator


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
        self.activation_bonuses = {HL: 0, WS: 0}
        self.combat_bonuses = {HL: 0, WS: 0}

        # Rule tags for country-specific activation logic.
        self.tag_knight_countries = "knight_countries"
        self.tower_country_id = "tower"
        self._movement_undo_stack = []
        self.victory_evaluator = None
        self.game_over = False
        self.winner = None
        self.victory_reason = ""
        self.victory_points = {HL: 0, WS: 0}

    @property
    def current_player(self):
        """Returns the Player object for the active_player allegiance."""
        return self.players.get(self.active_player)

    def get_player(self, allegiance: str):
        return self.players.get(allegiance)

    def end_game(self):
        pass

    def save_state(self, filename: str):
        phase_name = self.phase.name if hasattr(self.phase, "name") else str(self.phase)
        payload = {
            "metadata": {
                "scenario_id": self.scenario_spec.id if self.scenario_spec else None,
                "turn": self.turn,
                "phase": phase_name,
                "active_player": self.active_player,
                "initiative_winner": self.initiative_winner,
                "second_player_has_acted": self.second_player_has_acted,
                "activation_bonuses": dict(self.activation_bonuses),
                "combat_bonuses": dict(self.combat_bonuses),
            },
            "world_state": {
                "countries": {
                    cid: {
                        "allegiance": country.allegiance,
                        "conquered": bool(country.conquered),
                        "capital_id": country.capital_id,
                        "locations": {
                            lid: {"occupier": loc.occupier, "is_capital": bool(loc.is_capital)}
                            for lid, loc in country.locations.items()
                        },
                    }
                    for cid, country in self.countries.items()
                },
                "units": [u.to_dict() for u in self.units],
                "unit_runtime": {
                    f"{u.id}|{u.ordinal}": {
                        "movement_points": getattr(u, "movement_points", None),
                        "river_hexside": getattr(u, "river_hexside", None),
                        "replacement_ready_turn": getattr(u, "replacement_ready_turn", None),
                    }
                    for u in self.units
                },
                "players": {
                    allegiance: {
                        "is_ai": bool(player.is_ai),
                        "assets": [
                            {
                                "id": asset_id,
                                "assigned_to": (
                                    [asset.assigned_to.id, asset.assigned_to.ordinal]
                                    if getattr(asset, "assigned_to", None)
                                    else None
                                ),
                            }
                            for asset_id, asset in player.assets.items()
                        ],
                    }
                    for allegiance, player in self.players.items()
                },
                "completed_event_ids": sorted(self.completed_event_ids),
                "strategic_events": {
                    evt.id: {
                        "occurrence_count": evt.occurrence_count,
                        "is_active": evt.is_active,
                    }
                    for evt in self.strategic_event_pool
                },
            },
        }
        loader.save_game_state(path=filename, payload=payload)

    def load_state(self, filename):
        save_data = loader.load_game_state(filename)
        metadata = save_data.metadata or {}
        world_state = save_data.world_state or {}

        scenario_id = metadata.get("scenario_id")
        if not scenario_id:
            raise ValueError("Save file missing metadata.scenario_id")

        scenario_spec = self._find_scenario_spec_by_id(scenario_id)
        if not scenario_spec:
            raise ValueError(f"Scenario '{scenario_id}' not found in {SCENARIOS_DIR}")

        self.load_scenario(scenario_spec)

        self.turn = int(metadata.get("turn", self.turn))
        phase_raw = metadata.get("phase")
        if phase_raw:
            try:
                self.phase = GamePhase[phase_raw] if isinstance(phase_raw, str) else GamePhase(phase_raw)
            except Exception:
                pass
        self.active_player = metadata.get("active_player", self.active_player)
        self.initiative_winner = metadata.get("initiative_winner", self.initiative_winner)
        self.second_player_has_acted = bool(
            metadata.get("second_player_has_acted", self.second_player_has_acted)
        )
        saved_bonuses = metadata.get("activation_bonuses", {}) or {}
        self.activation_bonuses = {
            HL: int(saved_bonuses.get(HL, 0) or 0),
            WS: int(saved_bonuses.get(WS, 0) or 0),
        }
        saved_combat_bonuses = metadata.get("combat_bonuses", {}) or {}
        self.combat_bonuses = {
            HL: int(saved_combat_bonuses.get(HL, 0) or 0),
            WS: int(saved_combat_bonuses.get(WS, 0) or 0),
        }

        self._restore_countries_from_save(world_state.get("countries", {}))
        self._restore_units_from_save(
            world_state.get("units", []),
            world_state.get("unit_runtime", {}),
        )
        self._restore_players_from_save(world_state.get("players", {}))
        self._restore_events_from_save(world_state)
        self.clear_movement_undo()

    def load_scenario(self, scenario_spec):
        """
        Initializes the game state from scenario data.
        """
        builder = factory.ScenarioBuilder()
        builder.build(self, scenario_spec)
        self.victory_evaluator = VictoryConditionEvaluator(self)
        self.game_over = False
        self.winner = None
        self.victory_reason = ""
        self.victory_points = {HL: 0, WS: 0}

    def evaluate_victory_conditions(self):
        if not self.victory_evaluator:
            return None
        status = self.victory_evaluator.evaluate()
        self.victory_points = dict(status.minor_points)
        if status.game_over and not self.game_over:
            self.game_over = True
            self.winner = status.winner
            self.victory_reason = status.reason
        return status

    def _find_scenario_spec_by_id(self, scenario_id: str):
        scenarios_dir = Path(SCENARIOS_DIR)
        if not scenarios_dir.exists():
            return None
        for path in sorted(scenarios_dir.glob("*.yaml")):
            try:
                spec = loader.load_scenario_yaml(str(path))
            except Exception:
                continue
            if spec.id == scenario_id:
                return spec
        return None

    def _restore_countries_from_save(self, countries_state):
        if not isinstance(countries_state, dict):
            return
        for cid, state in countries_state.items():
            country = self.countries.get(cid)
            if not country or not isinstance(state, dict):
                continue
            country.allegiance = state.get("allegiance", country.allegiance)
            country.conquered = bool(state.get("conquered", country.conquered))
            if state.get("capital_id") in country.locations:
                country.capital_id = state["capital_id"]
                for loc in country.locations.values():
                    loc.is_capital = (loc.id == country.capital_id)

            for lid, loc_state in (state.get("locations", {}) or {}).items():
                if lid not in country.locations or not isinstance(loc_state, dict):
                    continue
                loc = country.locations[lid]
                loc.occupier = loc_state.get("occupier", loc.occupier)
                if "is_capital" in loc_state:
                    loc.is_capital = bool(loc_state["is_capital"])

    def _restore_units_from_save(self, units_state, unit_runtime_state):
        if not isinstance(units_state, list):
            return

        by_key = {(u.id, u.ordinal): u for u in self.units}
        transport_refs = []

        for state in units_state:
            if not isinstance(state, dict):
                continue
            key = (state.get("unit_id"), int(state.get("ordinal", 1) or 1))
            unit = by_key.get(key)
            if not unit:
                continue
            unit.load_state(state)
            runtime = (unit_runtime_state or {}).get(f"{unit.id}|{unit.ordinal}", {})
            if isinstance(runtime, dict):
                mp = runtime.get("movement_points")
                if mp is not None:
                    unit.movement_points = mp
                if hasattr(unit, "river_hexside"):
                    river_hexside = runtime.get("river_hexside")
                    if (
                        isinstance(river_hexside, (list, tuple))
                        and len(river_hexside) == 2
                        and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in river_hexside)
                    ):
                        unit.river_hexside = tuple((int(p[0]), int(p[1])) for p in river_hexside)
                    else:
                        unit.river_hexside = None
                if runtime.get("replacement_ready_turn") is not None:
                    unit.replacement_ready_turn = runtime.get("replacement_ready_turn")

            host_raw = state.get("transport_host")
            if host_raw:
                try:
                    host_key = (host_raw[0], int(host_raw[1]))
                    transport_refs.append((unit, host_key))
                except Exception:
                    pass

            if hasattr(unit, "passengers"):
                unit.passengers = []
            if hasattr(unit, "equipment"):
                unit.equipment = []

        for unit, host_key in transport_refs:
            host = by_key.get(host_key)
            if not host:
                unit.transport_host = None
                unit.is_transported = False
                continue
            unit.transport_host = host
            unit.is_transported = True
            if hasattr(host, "passengers") and unit not in host.passengers:
                host.passengers.append(unit)

        self.map.unit_map = defaultdict(list)
        for unit in self.units:
            if not unit.is_on_map or not unit.position or unit.position[0] is None or unit.position[1] is None:
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            self.map.add_unit_to_spatial_map(unit)

    def _restore_players_from_save(self, players_state):
        if not isinstance(players_state, dict):
            return

        by_key = {(u.id, u.ordinal): u for u in self.units}

        for allegiance, p_state in players_state.items():
            player = self.players.get(allegiance)
            if not player or not isinstance(p_state, dict):
                continue
            player.set_ai(bool(p_state.get("is_ai", player.is_ai)))
            player.assets = {}
            for asset_data in p_state.get("assets", []) or []:
                if not isinstance(asset_data, dict):
                    continue
                asset_id = asset_data.get("id")
                if not asset_id:
                    continue
                player.grant_asset(asset_id, self)
                asset = player.assets.get(asset_id)
                assigned = asset_data.get("assigned_to")
                if asset and assigned and isinstance(assigned, (list, tuple)) and len(assigned) == 2:
                    unit = by_key.get((assigned[0], int(assigned[1])))
                    if unit and asset.can_equip(unit):
                        asset.apply_to(unit)

    def _restore_events_from_save(self, world_state):
        completed_ids = world_state.get("completed_event_ids", [])
        self.completed_event_ids = set(completed_ids or [])
        strategic_state = world_state.get("strategic_events", {}) or {}
        for event in self.strategic_event_pool:
            state = strategic_state.get(event.id)
            if not isinstance(state, dict):
                continue
            event.occurrence_count = int(state.get("occurrence_count", event.occurrence_count))
            event.is_active = bool(state.get("is_active", event.is_active))

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

            initial_assets = setup_data.get("assets", None)
            if initial_assets is None:
                initial_assets = setup_data.get("artifacts", [])
            if initial_assets is None:
                initial_assets = []
            if isinstance(initial_assets, str):
                initial_assets = [initial_assets]
            elif isinstance(initial_assets, dict):
                expanded_assets = []
                for asset_id, qty in initial_assets.items():
                    if not asset_id:
                        continue
                    try:
                        amount = int(qty) if qty is not None else 1
                    except (TypeError, ValueError):
                        amount = 1
                    if amount <= 0:
                        continue
                    expanded_assets.extend([str(asset_id)] * amount)
                initial_assets = expanded_assets
            elif not isinstance(initial_assets, list):
                initial_assets = list(initial_assets) if isinstance(initial_assets, tuple) else []

            # Create spec from dictionary (handling potential missing keys)
            spec = PlayerSpec(
                allegiance=allegiance,
                deployment_area=deployment_area,
                country_deployment=country_deployment,
                setup_countries=setup_data.get("countries", {}),
                explicit_units=setup_data.get("explicit_units", []),
                victory_conditions=setup_data.get("victory_conditions", {}) or self.scenario_spec.victory_conditions.get(allegiance, {}),
                pre_req=setup_data.get("pre_req", []),
                artifacts=initial_assets,
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

            for asset_id in spec.artifacts:
                player.grant_asset(asset_id, self)

    def get_deployment_hexes(self, allegiance: str) -> Set[tuple]:
        return self.deployment_service.get_deployment_hexes(allegiance)

    def get_valid_deployment_hexes(self, unit, allow_territory_wide=False) -> List[Tuple[int, int]]:
        return self.deployment_service.get_valid_deployment_hexes(unit, allow_territory_wide=allow_territory_wide)

    def apply_conscription(self, kept_unit, discarded_unit):
        """Apply conscription result: keep one unit, destroy the other."""
        if kept_unit.unit_type == UnitType.FLEET:
            # Fleet replacements become READY on the next replacements turn.
            kept_unit.status = UnitState.INACTIVE
            kept_unit.replacement_ready_turn = self.turn + 1
        else:
            kept_unit.status = UnitState.READY

        discarded_unit.status = UnitState.DESTROYED
        discarded_unit.position = (None, None)

    def process_delayed_fleet_replacements(self):
        """
        Promotes fleets recovered by conscription to READY at the start of a later replacement turn.
        """
        for unit in self.units:
            if unit.unit_type != UnitType.FLEET:
                continue
            ready_turn = getattr(unit, "replacement_ready_turn", None)
            if ready_turn is None:
                continue
            if self.turn >= ready_turn and unit.status == UnitState.INACTIVE:
                unit.status = UnitState.READY
                delattr(unit, "replacement_ready_turn")

    def get_replacement_group_key(self, unit):
        """
        Group key for replacement/conscription pairing.
        - Armies: same country OR same dragonflight.
        - Fleets: same country only.
        """
        if unit.unit_type == UnitType.FLEET:
            return ("fleet", unit.land)
        if hasattr(unit, "is_army") and unit.is_army():
            dragonflight = getattr(unit.spec, "dragonflight", None)
            return ("army", dragonflight or unit.land)
        return (None, None)

    def can_conscript_pair(self, unit_a, unit_b) -> bool:
        """
        Validates replacement/conscription pair eligibility without mixing unit types.
        """
        key_a = self.get_replacement_group_key(unit_a)
        key_b = self.get_replacement_group_key(unit_b)
        return key_a[0] is not None and key_a == key_b

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

    def has_neutral_countries(self) -> bool:
        return any(country.allegiance == NEUTRAL for country in self.countries.values())

    def add_activation_bonus(self, allegiance: str, amount: int):
        if allegiance not in self.activation_bonuses:
            return
        self.activation_bonuses[allegiance] += int(amount)

    def get_activation_bonus(self, allegiance: str) -> int:
        return int(self.activation_bonuses.get(allegiance, 0))

    def get_country_activation_bonus(self, allegiance: str, country_id: str) -> int:
        """
        Artifact diplomacy bonus:
        +1 target activation rating per equipped artifact that lists `country_id`,
        as long as both unit and artifact are not DESTROYED.
        """
        if not country_id:
            return 0
        total = 0
        country_key = str(country_id).lower()
        for unit in self.units:
            if getattr(unit, "allegiance", None) != allegiance:
                continue
            if getattr(unit, "status", None) == UnitState.DESTROYED:
                continue
            for asset in getattr(unit, "equipment", []) or []:
                if not isinstance(getattr(asset, "bonus", None), dict):
                    continue
                targets = asset.bonus.get("diplomacy")
                if not isinstance(targets, list):
                    continue
                if not any(str(cid).lower() == country_key for cid in targets):
                    continue
                owner = getattr(asset, "owner", None)
                if owner and hasattr(owner, "assets"):
                    if getattr(asset, "id", None) not in owner.assets:
                        continue
                if getattr(asset, "assigned_to", None) is not unit:
                    continue
                total += 1
        return total

    def clear_activation_bonuses(self):
        for key in list(self.activation_bonuses.keys()):
            self.activation_bonuses[key] = 0

    def add_combat_bonus(self, allegiance: str, amount: int):
        if allegiance not in self.combat_bonuses:
            return
        self.combat_bonuses[allegiance] += int(amount)

    def get_combat_bonus(self, allegiance: str) -> int:
        return int(self.combat_bonuses.get(allegiance, 0))

    def clear_combat_bonus(self, allegiance: str):
        if allegiance not in self.combat_bonuses:
            return
        self.combat_bonuses[allegiance] = 0

    def clear_combat_bonuses(self):
        for key in list(self.combat_bonuses.keys()):
            self.combat_bonuses[key] = 0

    def _force_move_fleet_to_state(self, fleet, state):
        retreat_hex, retreat_side = state
        self.map.remove_unit_from_spatial_map(fleet)
        fleet.position = retreat_hex.axial_to_offset()
        fleet.river_hexside = retreat_side
        if hasattr(fleet, "moved_this_turn"):
            fleet.moved_this_turn = True
        self.map.add_unit_to_spatial_map(fleet)

        passengers = getattr(fleet, "passengers", None)
        if passengers:
            for passenger in passengers:
                passenger.position = fleet.position
                passenger.is_transported = True
                passenger.transport_host = fleet

    def _displace_enemy_fleets_in_hex(self, invading_unit, target_hex):
        units_in_hex = list(self.map.get_units_in_hex(target_hex.q, target_hex.r))
        enemy_fleets = [
            u for u in units_in_hex
            if (
                u is not invading_unit
                and u.unit_type == UnitType.FLEET
                and getattr(u, "is_on_map", True)
                and u.allegiance not in (invading_unit.allegiance, NEUTRAL)
            )
        ]

        for fleet in enemy_fleets:
            if not fleet.position or fleet.position[0] is None or fleet.position[1] is None:
                continue
            start_hex = Hex.offset_to_axial(*fleet.position)
            retreat_state = self.map.find_nearest_safe_fleet_state(fleet, start_hex)
            if retreat_state is None:
                print(f"No legal displacement hex found for fleet {fleet.id}.")
                continue
            self._force_move_fleet_to_state(fleet, retreat_state)

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
        fleet_final_hexside = getattr(unit, "river_hexside", None)
        if self.phase == GamePhase.MOVEMENT and unit.position:
            ok, _, cost, _, state_path = evaluate_unit_move(self, unit, target_hex)
            if not ok:
                return

            # Ensure attribute exists (defensive coding)
            if not hasattr(unit, 'movement_points'):
                unit.movement_points = unit.movement

            if unit.unit_type == UnitType.FLEET and state_path:
                fleet_final_hexside = state_path[-1][1]
                for i in range(1, len(state_path)):
                    prev_hex, prev_side = state_path[i - 1]
                    curr_hex, curr_side = state_path[i]
                    if prev_side is None and curr_side is not None:
                        print(f"Fleet {unit.id} enters deep_river hexside {curr_side} (hex -> hexside).")
                    elif prev_side is not None and curr_side is None:
                        print(f"Fleet {unit.id} exits deep_river at hex {curr_hex.axial_to_offset()} (hexside -> hex).")
                    elif prev_side is not None and curr_side != prev_side:
                        print(f"Fleet {unit.id} moves along deep_river to hexside {curr_side}.")

            effective_mp = effective_movement_points(unit)
            if cost > effective_mp:
                return
            unit.movement_points = max(0, effective_mp - cost)

        # 2. Update Position
        # Remove from old position in spatial map
        self.map.remove_unit_from_spatial_map(unit)

        # Update Unit's internal state (store as offset col, row for persistence/view)
        offset_coords = target_hex.axial_to_offset()
        unit.escaped = False
        unit.position = offset_coords

        # Add to new position in spatial map
        self.map.add_unit_to_spatial_map(unit)

        if self.phase == GamePhase.MOVEMENT:
            unit.moved_this_turn = True
            if unit.unit_type == UnitType.FLEET:
                unit.river_hexside = fleet_final_hexside

        # If this unit is a carrier (Fleet/Wing/Citadel) move its passengers implicitly
        passengers = getattr(unit, 'passengers', None)
        if passengers:
            for p in passengers:
                # Update passenger state to remain transported; do NOT add them to spatial map
                p.position = unit.position
                p.is_transported = True
                p.transport_host = unit
                if self.phase == GamePhase.MOVEMENT and unit.unit_type == UnitType.CITADEL:
                    p.carried_by_citadel_this_turn = True

        # Rule: Ground armies displace enemy fleets from the entered hex.
        if (
            hasattr(unit, "is_army")
            and unit.is_army()
            and unit.unit_type not in (UnitType.FLEET, UnitType.WING)
        ):
            self._displace_enemy_fleets_in_hex(unit, target_hex)

        self._apply_escape_if_eligible(unit, offset_coords)

    def _apply_escape_if_eligible(self, unit, target_offset):
        if self.phase != GamePhase.MOVEMENT:
            return
        if not self.victory_evaluator:
            return
        side = getattr(unit, "allegiance", None)
        if side not in (HL, WS):
            return

        rules = self.victory_evaluator.get_escape_rules_for_side(side, self.turn)
        if not rules:
            return
        for rule in rules:
            if self.victory_evaluator.unit_matches_escape_rule(unit, target_offset, rule, side):
                self._mark_unit_escaped(unit)
                break

    def _mark_unit_escaped(self, unit):
        self.map.remove_unit_from_spatial_map(unit)
        unit.position = (None, None)
        unit.escaped = True
        unit.is_transported = False
        unit.transport_host = None
        if hasattr(unit, "river_hexside"):
            unit.river_hexside = None

        passengers = list(getattr(unit, "passengers", []) or [])
        for passenger in passengers:
            self.map.remove_unit_from_spatial_map(passenger)
            passenger.position = (None, None)
            passenger.escaped = True
            passenger.is_transported = False
            passenger.transport_host = None
        if hasattr(unit, "passengers"):
            unit.passengers = []

    def clear_movement_undo(self):
        self._movement_undo_stack.clear()

    def can_undo_movement(self):
        return bool(self._movement_undo_stack)

    def push_movement_undo_snapshot(self):
        """
        Stores a full-unit snapshot before a movement action.
        Snapshot scope is turn/player-bound so undo cannot cross turns or active player.
        """
        unit_states = []
        for unit in self.units:
            unit_states.append({
                "unit": unit,
                "position": tuple(unit.position) if getattr(unit, "position", None) else (None, None),
                "status": unit.status,
                "movement_points": getattr(unit, "movement_points", None),
                "moved_this_turn": getattr(unit, "moved_this_turn", False),
                "attacked_this_turn": getattr(unit, "attacked_this_turn", False),
                "is_transported": getattr(unit, "is_transported", False),
                "carried_by_citadel_this_turn": getattr(unit, "carried_by_citadel_this_turn", False),
                "transport_host": getattr(unit, "transport_host", None),
                "river_hexside": getattr(unit, "river_hexside", None),
                "passengers": list(getattr(unit, "passengers", [])),
                "escaped": bool(getattr(unit, "escaped", False)),
            })
        self._movement_undo_stack.append({
            "turn": self.turn,
            "active_player": self.active_player,
            "units": unit_states,
        })

    def discard_last_movement_snapshot(self):
        if self._movement_undo_stack:
            self._movement_undo_stack.pop()

    def undo_last_movement(self):
        if not self._movement_undo_stack:
            return False

        snapshot = self._movement_undo_stack.pop()
        if snapshot["turn"] != self.turn or snapshot["active_player"] != self.active_player:
            self._movement_undo_stack.clear()
            return False

        for state in snapshot["units"]:
            unit = state["unit"]
            unit.position = state["position"]
            unit.status = state["status"]
            if state["movement_points"] is not None:
                unit.movement_points = state["movement_points"]
            unit.moved_this_turn = state["moved_this_turn"]
            unit.attacked_this_turn = state["attacked_this_turn"]
            unit.is_transported = state["is_transported"]
            unit.carried_by_citadel_this_turn = state.get("carried_by_citadel_this_turn", False)
            unit.transport_host = state["transport_host"]
            if hasattr(unit, "river_hexside"):
                unit.river_hexside = state["river_hexside"]
            if hasattr(unit, "passengers"):
                unit.passengers = list(state["passengers"])
            unit.escaped = bool(state.get("escaped", False))

        # Rebuild spatial map after restoring all unit states.
        self.map.unit_map = defaultdict(list)
        for unit in self.units:
            pos = getattr(unit, "position", None)
            if not pos or pos[0] is None or pos[1] is None:
                continue
            if not getattr(unit, "is_on_map", False):
                continue
            if getattr(unit, "transport_host", None) is not None:
                continue
            self.map.add_unit_to_spatial_map(unit)

        return True

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
                    occupying_units = [
                        u for u in self.map.get_units_in_hex(hex_obj.q, hex_obj.r)
                        if (
                            u.is_on_map
                            and u.allegiance == enemy
                            and (
                                (hasattr(u, "is_army") and u.is_army())
                                or u.unit_type == UnitType.WING
                            )
                        )
                    ]
                    if occupying_units:
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
        - Fleets remain only if currently on map (ACTIVE/DEPLETED).
        """
        destroyed_count = 0
        for unit in self.units:
            if unit.land != country.id:
                continue

            if unit.unit_type == UnitType.FLEET:
                if unit.status not in UnitState.on_map_states() and unit.status != UnitState.DESTROYED:
                    unit.destroy()
                    self.map.remove_unit_from_spatial_map(unit)
                    destroyed_count += 1
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

    def _enforce_conquered_fleet_replacement_rule(self):
        """
        Fleets from conquered countries that reach RESERVE are DESTROYED,
        except for knight-country fleets while at least one knight country is unconquered.
        """
        any_knight_unconquered = any(
            (not c.conquered) for c in self._countries_with_tag(self.tag_knight_countries)
        )

        for unit in self.units:
            if unit.unit_type != UnitType.FLEET or unit.status != UnitState.RESERVE:
                continue
            country = self.countries.get(unit.land)
            if not country or not country.conquered:
                continue

            is_knight_country = self._country_has_tag(country, self.tag_knight_countries)
            if is_knight_country and any_knight_unconquered:
                continue

            unit.destroy()
            self.map.remove_unit_from_spatial_map(unit)

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
        self._enforce_conquered_fleet_replacement_rule()

    def _resolve_add_units(self, unit_key: str, allegiance: str):
        self.event_system._resolve_add_units(unit_key, allegiance)

    def apply_event_effect(self, spec):
        return self.event_system.apply_event_effect(spec)

    def draw_strategic_event(self, allegiance):
        return self.event_system.draw_strategic_event(allegiance)

    def resolve_event(self, event):
        pass

    def resolve_combat(
        self,
        attackers,
        hex_position,
        naval_withdraw_decider=None,
        dragon_duel_withdraw_decider=None,
    ):
        """
        Initiates combat resolution for a specific hex.
        """
        attackers = list(attackers)
        defenders = list(self.get_units_at(hex_position))
        terrain = self.map.get_terrain(hex_position)
        defender_allegiances = {
            u.allegiance for u in defenders
            if u.allegiance not in ("neutral", None)
        }

        # Leader-only defender stacks attacked by armies/wings do not resolve normal combat.
        # Each defending leader performs leader-escape mechanics instead.
        if self._is_leader_only_stack(defenders) and self._attack_triggers_leader_stack_escape(attackers):
            leader_origins = {
                u: Hex.offset_to_axial(*u.position)
                for u in defenders
                if hasattr(u, "is_leader") and u.is_leader() and u.position and u.position[0] is not None
            }
            # Force escape checks for each defending leader in the attacked leader-only stack.
            leader_stack_has_army = {leader: True for leader in leader_origins.keys()}
            leader_escape_requests = self._resolve_leader_escapes(leader_origins, leader_stack_has_army)
            result = "-/-"
            print(self._format_combat_log_entry(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": leader_escape_requests or [],
                "advance_available": False,
            }

        if self._combat_blocked_by_citadel_rule(attackers, defenders):
            result = "-/-"
            print(self._format_combat_log_entry(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }
        attackers = self._filter_ws_ground_attackers_vs_citadel(attackers, defenders)
        if not self.can_units_attack_stack(attackers, defenders):
            result = "-/-"
            print(self._format_combat_log_entry(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }
        if not attackers:
            result = "-/-"
            print(self._format_combat_log_entry(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }

        if self._is_naval_combat(attackers, defenders):
            naval_resolver = NavalCombatResolver(self, attackers, defenders)
            outcome = naval_resolver.resolve(withdraw_decider=naval_withdraw_decider)
            self._cleanup_destroyed_units(attackers + defenders)
            print(self._format_naval_log_entry(attackers, defenders, outcome))
            return {
                "result": outcome.get("result", "-/-"),
                "leader_escape_requests": [],
                "advance_available": False,
                "combat_type": "naval",
                "rounds": outcome.get("rounds", 0),
            }

        for msg in self._apply_combat_healing(attackers + defenders):
            print(msg)

        orb_events = apply_dragon_orb_bonus(
            attackers,
            defenders,
            consume_asset_fn=self._consume_asset,
        )
        if orb_events:
            self._cleanup_destroyed_units(attackers + defenders)
            attackers = [u for u in attackers if u.is_on_map]
            defenders = list(self.get_units_at(hex_position))
            for evt in orb_events:
                print(evt)

            if not any(self._is_combat_stack_unit(u) for u in defenders):
                result = "-/-"
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
            if not any(self._is_combat_stack_unit(u) for u in attackers):
                result = "-/-"
                print(self._format_combat_log_entry(attackers, defenders, result))
                return {
                    "result": result,
                    "leader_escape_requests": [],
                    "advance_available": False,
                }

        attacker_dragons = [u for u in attackers if self._is_dragon_unit(u) and u.is_on_map]
        defender_dragons = [u for u in defenders if self._is_dragon_unit(u) and u.is_on_map]
        if attacker_dragons and defender_dragons:
            duel = DragonDuelResolver(self, attacker_dragons, defender_dragons)
            duel_outcome = duel.resolve(withdraw_decider=dragon_duel_withdraw_decider)
            print(
                f"Dragon duel after {duel_outcome.get('rounds', 0)} rounds: "
                f"A={duel_outcome.get('attacker_survivors', 0)} D={duel_outcome.get('defender_survivors', 0)}"
            )
            self._cleanup_destroyed_units(attackers + defenders)
            attackers = [u for u in attackers if u.is_on_map]
            defenders = list(self.get_units_at(hex_position))
            if not any(self._is_combat_stack_unit(u) for u in defenders):
                result = "-/-"
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

        attackers = self._filter_dragons_for_land_attack(attackers, defenders)
        if not any(self._is_combat_stack_unit(u) for u in attackers):
            result = "-/-"
            print(self._format_combat_log_entry(attackers, defenders, result))
            return {
                "result": result,
                "leader_escape_requests": [],
                "advance_available": False,
            }

        gnome_drm = 0
        gnome_effects, gnome_logs = apply_gnome_tech_bonus(
            attackers,
            defenders,
            consume_asset_fn=self._consume_asset,
        )
        for msg in gnome_logs:
            print(msg)
        gnome_drm += int(gnome_effects.get("attacker", 0))
        gnome_drm += int(gnome_effects.get("defender", 0))

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

        resolver = CombatResolver(
            attackers,
            defenders,
            terrain,
            game_state=self,
            precombat_drm_bonus=gnome_drm,
            allow_consumable_other_bonus=True,
        )
        result = resolver.resolve()
        print(self._format_combat_log_entry(attackers, defenders, result))
        self._cleanup_destroyed_units(attackers + defenders)
        revive_escape_requests = self._resolve_leader_revives(attackers + defenders, leader_origins)
        leader_escape_requests = self._resolve_leader_escapes(leader_origins, leader_stack_has_army)
        leader_escape_requests = (revive_escape_requests or []) + (leader_escape_requests or [])

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

    def _apply_combat_healing(self, units):
        logs = []
        for unit in units:
            if getattr(unit, "status", None) != UnitState.DEPLETED:
                continue
            if getattr(unit, "_healed_this_combat_turn", False):
                continue
            healing_asset = self._get_equipped_other_bonus_asset(unit, "healing")
            if healing_asset is None:
                continue
            unit.status = UnitState.ACTIVE
            unit._healed_this_combat_turn = True
            logs.append(f"Healing activated: {unit.id} restored to ACTIVE.")
            if getattr(healing_asset, "is_consumable", False):
                self._consume_asset(healing_asset, unit)
                logs.append(f"Healing asset consumed: {healing_asset.id} on {unit.id}.")
        return logs

    def _get_equipped_other_bonus_asset(self, unit, bonus_name):
        for asset in getattr(unit, "equipment", []) or []:
            bonus = getattr(asset, "bonus", None)
            if isinstance(bonus, dict) and bonus.get("other") == bonus_name:
                return asset
        return None

    def _resolve_leader_revives(self, units, leader_origins):
        requests = []
        for leader in units:
            if not (hasattr(leader, "is_leader") and leader.is_leader()):
                continue
            if getattr(leader, "status", None) != UnitState.DESTROYED:
                continue
            revive_asset = self._get_equipped_other_bonus_asset(leader, "revive")
            if revive_asset is None:
                continue

            origin_hex = leader_origins.get(leader)
            if not origin_hex:
                continue
            options = self._get_nearest_friendly_combat_stacks(leader, origin_hex)
            if not options:
                continue

            leader.status = UnitState.ACTIVE
            leader.position = (None, None)
            requests.append(LeaderEscapeRequest(leader=leader, options=options))
            print(f"Revive activated: {leader.id} may escape to nearest friendly stack.")
            if getattr(revive_asset, "is_consumable", False):
                self._consume_asset(revive_asset, leader)
        return requests

    def _consume_asset(self, asset, unit):
        if hasattr(asset, "remove_from"):
            asset.remove_from(unit)
        else:
            if hasattr(unit, "equipment") and asset in unit.equipment:
                unit.equipment.remove(asset)
            asset.assigned_to = None

        if getattr(asset, "owner", None) and hasattr(asset.owner, "assets"):
            asset.owner.assets.pop(asset.id, None)
            return

        for player in self.players.values():
            if not hasattr(player, "assets"):
                continue
            candidate = player.assets.get(getattr(asset, "id", None))
            if candidate is asset or (candidate and getattr(candidate, "id", None) == getattr(asset, "id", None)):
                player.assets.pop(asset.id, None)
                return

    def can_units_attack_stack(self, attackers, defenders):
        attackers = [u for u in attackers if getattr(u, "is_on_map", False)]
        defenders = [u for u in defenders if getattr(u, "is_on_map", False)]
        if not attackers or not defenders:
            return False

        defenders_have_dragons = any(self._is_dragon_unit(u) for u in defenders)
        for unit in attackers:
            if not self._is_combat_stack_unit(unit):
                continue
            if not self._is_dragon_unit(unit):
                return True
            if defenders_have_dragons:
                return True
            if self._dragon_can_make_ground_attack(unit, attackers):
                return True
        return False

    def _filter_dragons_for_land_attack(self, attackers, defenders):
        filtered = []
        for unit in attackers:
            if not getattr(unit, "is_on_map", False):
                continue
            if self._dragon_can_participate_in_land_attack(unit, attackers, defenders):
                filtered.append(unit)
        return filtered

    def _dragon_can_participate_in_land_attack(self, unit, attackers, defenders):
        if not self._is_dragon_unit(unit):
            return True
        return self._dragon_can_make_ground_attack(unit, attackers)

    def _dragon_can_make_ground_attack(self, dragon, attackers):
        if not self._is_dragon_unit(dragon):
            return True

        if dragon.allegiance == HL and self._all_highlords_destroyed():
            return False
        if dragon.allegiance == WS and self._all_ws_dragon_commanders_destroyed():
            return False

        return self._dragon_has_local_attack_leader(dragon, attackers)

    def _dragon_has_local_attack_leader(self, dragon, attackers):
        local_leaders = []
        for unit in attackers:
            if not (hasattr(unit, "is_leader") and unit.is_leader()):
                continue
            if getattr(unit, "allegiance", None) != dragon.allegiance:
                continue
            if getattr(unit, "position", None) != getattr(dragon, "position", None):
                continue
            local_leaders.append(unit)

        for p in list(getattr(dragon, "passengers", []) or []):
            if hasattr(p, "is_leader") and p.is_leader() and getattr(p, "allegiance", None) == dragon.allegiance:
                local_leaders.append(p)

        if dragon.allegiance == HL:
            return any(self._is_valid_hl_dragon_commander(leader, dragon) for leader in local_leaders)
        if dragon.allegiance == WS:
            return any(self._is_valid_ws_dragon_commander(leader) for leader in local_leaders)
        return False

    def _is_valid_hl_dragon_commander(self, leader, dragon):
        if getattr(leader, "unit_type", None) == UnitType.EMPEROR:
            return True
        if getattr(leader, "unit_type", None) != UnitType.HIGHLORD:
            return False
        leader_flight = getattr(getattr(leader, "spec", None), "dragonflight", None)
        dragon_flight = getattr(getattr(dragon, "spec", None), "dragonflight", None)
        return bool(leader_flight and dragon_flight and leader_flight == dragon_flight)

    def _is_valid_ws_dragon_commander(self, leader):
        return getattr(leader, "race", None) in (UnitRace.SOLAMNIC, UnitRace.ELF)

    def _all_highlords_destroyed(self):
        highlords = [u for u in self.units if getattr(u, "unit_type", None) == UnitType.HIGHLORD]
        return bool(highlords) and all(getattr(u, "status", None) == UnitState.DESTROYED for u in highlords)

    def _all_ws_dragon_commanders_destroyed(self):
        ws_commanders = [
            u for u in self.units
            if getattr(u, "allegiance", None) == WS
            and hasattr(u, "is_leader")
            and u.is_leader()
            and getattr(u, "race", None) in (UnitRace.SOLAMNIC, UnitRace.ELF)
        ]
        return bool(ws_commanders) and all(getattr(u, "status", None) == UnitState.DESTROYED for u in ws_commanders)

    def _is_dragon_unit(self, unit):
        return bool(getattr(unit, "is_on_map", False) and getattr(unit, "race", None) == UnitRace.DRAGON)

    def _maybe_promote_highlord_to_emperor(self):
        living_emperors = [
            u for u in self.units
            if getattr(u, "unit_type", None) == UnitType.EMPEROR
            and getattr(u, "status", None) != UnitState.DESTROYED
        ]
        if living_emperors:
            return None

        candidates = [
            u for u in self.units
            if getattr(u, "unit_type", None) == UnitType.HIGHLORD
            and hasattr(u, "is_leader")
            and u.is_leader()
            and getattr(u, "status", None) != UnitState.DESTROYED
        ]
        if not candidates:
            return None

        promoted = random.choice(candidates)
        promoted._unit_type_override = UnitType.EMPEROR
        self._notify_emperor_promotion(promoted)
        return promoted

    def _notify_emperor_promotion(self, promoted):
        msg = f"{promoted.id} has been promoted to Emperor."
        print(msg)
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                QMessageBox.information(None, "Highlord Command", msg)
        except Exception:
            pass

    def _is_naval_combat(self, attackers, defenders):
        atk_fleets = [u for u in attackers if u.unit_type == UnitType.FLEET and u.is_on_map]
        if not atk_fleets or len(atk_fleets) != len([u for u in attackers if u.is_on_map]):
            return False
        def_fleets = [u for u in defenders if u.unit_type == UnitType.FLEET and u.is_on_map and u.allegiance != self.active_player]
        return bool(def_fleets)

    def _fleet_attack_nodes(self, fleet):
        if not fleet.position or fleet.position[0] is None or fleet.position[1] is None:
            return []
        nodes = []
        start_hex = Hex.offset_to_axial(*fleet.position)
        nodes.append(start_hex)
        river_side = getattr(fleet, "river_hexside", None)
        if river_side:
            endpoints = self.map._river_endpoints_local(river_side)
            for ep in endpoints:
                if ep not in nodes:
                    nodes.append(ep)
        return nodes

    def _fleets_are_adjacent_for_combat(self, attacker_fleet, defender_fleet):
        attacker_nodes = self._fleet_attack_nodes(attacker_fleet)
        defender_nodes = self._fleet_attack_nodes(defender_fleet)
        if not attacker_nodes or not defender_nodes:
            return False
        for a in attacker_nodes:
            for d in defender_nodes:
                if a == d:
                    return True
                if d in a.neighbors():
                    return True
        return False

    def can_fleet_attack_hex(self, fleet, target_hex):
        if fleet.unit_type != UnitType.FLEET or not fleet.is_on_map:
            return False
        defenders = [
            u for u in self.get_units_at(target_hex)
            if u.unit_type == UnitType.FLEET
            and u.allegiance != fleet.allegiance
            and u.allegiance != NEUTRAL
            and u.is_on_map
        ]
        if not defenders:
            return False
        return any(self._fleets_are_adjacent_for_combat(fleet, d) for d in defenders)

    def _format_naval_log_entry(self, attackers, defenders, outcome):
        attacker_names = ", ".join(self._format_unit_for_log(u) for u in attackers if u.unit_type == UnitType.FLEET)
        defender_names = ", ".join(self._format_unit_for_log(u) for u in defenders if u.unit_type == UnitType.FLEET)
        rounds = outcome.get("rounds", 0)
        result = outcome.get("result", "-/-")
        return f"Naval combat {result} after {rounds} rounds: Attackers [{attacker_names}] vs Defenders [{defender_names}]"

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
            or unit.unit_type in (UnitType.INFANTRY, UnitType.CAVALRY, UnitType.WING, UnitType.CITADEL)
        )

    @staticmethod
    def _is_leader_only_stack(units):
        live_units = [u for u in units if getattr(u, "is_on_map", False)]
        if not live_units:
            return False
        return all(hasattr(u, "is_leader") and u.is_leader() for u in live_units)

    @staticmethod
    def _attack_triggers_leader_stack_escape(attackers):
        return any(
            (
                (hasattr(u, "is_army") and u.is_army())
                or getattr(u, "unit_type", None) == UnitType.WING
            )
            and getattr(u, "is_on_map", False)
            for u in attackers
        )

    def _defenders_have_citadel(self, defenders):
        return any(u.unit_type == UnitType.CITADEL and getattr(u, "is_on_map", False) for u in defenders)

    def _is_ws_ground_combat_unit(self, unit):
        if unit.allegiance != WS or not getattr(unit, "is_on_map", False):
            return False
        if not (hasattr(unit, "is_army") and unit.is_army()):
            return False
        return unit.unit_type not in (UnitType.WING, UnitType.FLEET)

    def _is_ws_air_combat_unit(self, unit):
        return bool(unit.allegiance == WS and getattr(unit, "is_on_map", False) and unit.unit_type in (UnitType.WING, UnitType.CITADEL))

    def _combat_blocked_by_citadel_rule(self, attackers, defenders):
        if not self._defenders_have_citadel(defenders):
            return False
        has_ws_ground = any(self._is_ws_ground_combat_unit(u) for u in attackers)
        has_ws_air = any(self._is_ws_air_combat_unit(u) for u in attackers)
        return has_ws_ground and not has_ws_air

    def _filter_ws_ground_attackers_vs_citadel(self, attackers, defenders):
        if not self._defenders_have_citadel(defenders):
            return list(attackers)
        return [u for u in attackers if not self._is_ws_ground_combat_unit(u)]

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
        emperor_destroyed = any(
            getattr(unit, "unit_type", None) == UnitType.EMPEROR
            and getattr(unit, "status", None) == UnitState.DESTROYED
            for unit in units
        )
        for unit in units:
            if not unit.is_on_map or not unit.position or unit.position[0] is None or unit.position[1] is None:
                self.map.remove_unit_from_spatial_map(unit)
        if emperor_destroyed:
            self._maybe_promote_highlord_to_emperor()

    def board_unit(self, carrier, unit):
        """Boards `unit` onto `carrier` if allowed.
        Removes the unit from the spatial map, marks it transported and records transport_host.
        Returns True on success, False otherwise.
        """
        # Rule: a Wing cannot move and then load a unit in the same turn.
        if carrier.unit_type == UnitType.WING and getattr(carrier, "moved_this_turn", False):
            return False

        # Rule: armies can board a flying citadel only if they have not moved this turn.
        if carrier.unit_type == UnitType.CITADEL and getattr(unit, "moved_this_turn", False):
            return False

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

        # If transport load changes carrier movement allowance (e.g. Wing with passengers),
        # clamp remaining movement immediately to avoid range/deduction mismatches.
        if hasattr(carrier, "movement_points"):
            carrier.movement_points = min(carrier.movement_points, carrier.movement)
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

        if not self.map.can_unit_land_on_hex(unit, dest_hex):
            return False

        # Validate stacking limits
        moving_units = [unit]
        if not self.map.can_stack_move_to(moving_units, dest_hex):
            return False

        # Perform unboard: remove stale passenger refs, clear transport flags, add to spatial map
        if hasattr(carrier, "passengers"):
            while unit in carrier.passengers:
                carrier.passengers.remove(unit)
        for maybe_carrier in self.units:
            if maybe_carrier is carrier:
                continue
            passengers = getattr(maybe_carrier, "passengers", None)
            if passengers and unit in passengers:
                while unit in passengers:
                    passengers.remove(unit)
        unit.transport_host = None
        unit.is_transported = False
        # Place unit into dest offset coords
        offset_coords = dest_hex.axial_to_offset()
        self.map.remove_unit_from_spatial_map(unit)
        unit.position = offset_coords
        self.map.add_unit_to_spatial_map(unit)
        return True
