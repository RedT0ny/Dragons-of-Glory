import random
from collections import defaultdict, deque
from pathlib import Path
from typing import Set, Tuple, List, Dict, Optional

from content.tools import TextFormatter
from content.translator import Translator
from src.game.combat import CombatService
from src.game.diplomacy import ConquestService
from src.game.leader_escape import LeaderEscapeCheck, LeaderEscapeHandler
from src.content.config import MAP_WIDTH, MAP_HEIGHT, SCENARIOS_DIR
from src.content.constants import DEFAULT_MOVEMENT_POINTS, HL, WS, NEUTRAL
from src.content.specs import GamePhase, UnitState, UnitRace, LocationSpec, EventType, UnitType, LocType, TerrainType, HexsideType
from src.content import loader, factory
from src.game.map import Board, Hex
from src.game.deployment import DeploymentService
from src.game.event_system import EventSystem
from src.game.movement import MovementService
from src.game.phase_manager import PhaseManager, CalendarService
from src.game.victory import VictoryConditionEvaluator
from src.game import board_analysis
from src.game.overlay_maps import (
    PoliticalMap,
    ControlMap,
    TerritoryMap,
    SupplyMap,
    InfluenceMap,
    ThreatMap,
)

_KEEP_FIELD = object()


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
        self.movement_service = MovementService(self)
        self.combat_service = CombatService(self)
        self.conquest_service = ConquestService(self)
        self.calendar = CalendarService()
        self.translator = Translator()

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
        self.supply = "standard"

        # Rule tags for country-specific activation logic.
        self.tag_knight_countries = "knight_countries"
        self.tower_country_id = "tower"
        self.victory_evaluator = None
        self.game_over = False
        self.winner = None
        self.victory_reason = ""
        self.victory_points = {HL: 0, WS: 0}
        self._leader_escape_handler = None
        self._overlays = {}
        self._overlay_cache = {}
        self._overlay_dirty = set()
        self.territory_overrides = {}
        self._analysis_cache = {}
        self._analysis_dirty = set()

    @property
    def current_player(self):
        """Returns the Player object for the active_player allegiance."""
        return self.players.get(self.active_player)

    def has_human_player(self) -> bool:
        players = getattr(self, "players", {}) or {}
        return any(not getattr(player, "is_ai", False) for player in players.values())

    def are_all_players_ai(self) -> bool:
        players = getattr(self, "players", {}) or {}
        return bool(players) and all(bool(getattr(player, "is_ai", False)) for player in players.values())

    def get_player(self, allegiance: str):
        return self.players.get(allegiance)

    def _init_overlays(self):
        self._overlays = {
            "political": PoliticalMap(),
            "control": ControlMap(),
            "territory": TerritoryMap(),
            "supply": SupplyMap(),
            "ws_power": InfluenceMap(WS),
            "hl_power": InfluenceMap(HL),
            "threat": ThreatMap(),
        }
        self._overlay_cache = {}
        self._overlay_dirty = set(self._overlays.keys())
        self._analysis_cache = {}
        self._analysis_dirty = set()

    def invalidate_overlays(self, names=None):
        if not self._overlays:
            return
        if names is None:
            self._overlay_dirty = set(self._overlays.keys())
            return
        if isinstance(names, str):
            names = {names}
        self._overlay_dirty.update(set(names))

    def invalidate_analysis(self, names=None):
        if names is None:
            self._analysis_dirty = set(self._analysis_cache.keys())
            return
        if isinstance(names, str):
            names = {names}
        self._analysis_dirty.update(set(names))

    def finalize_board_state_change(self):
        self.invalidate_analysis({"control_facts"})
        self.update_territory_overrides()
        self.invalidate_overlays({"control", "territory", "supply", "ws_power", "hl_power", "threat"})

    def get_overlay(self, name: str):
        if not self._overlays:
            self._init_overlays()
        overlay = self._overlays.get(name)
        if overlay is None:
            return None
        if name in self._overlay_dirty or name not in self._overlay_cache:
            self._overlay_cache[name] = overlay.compute(self)
            self._overlay_dirty.discard(name)
        return self._overlay_cache.get(name)

    def get_control_facts(self):
        key = "control_facts"
        if key in self._analysis_dirty or key not in self._analysis_cache:
            self._analysis_cache[key] = board_analysis.compute_control_facts(self)
            self._analysis_dirty.discard(key)
        return self._analysis_cache.get(key)

    def can_unit_project_across_hexside(self, unit, from_hex, to_hex) -> bool:
        if not self.map or unit is None:
            return False
        if unit.is_fleet():
            return False
        cost = self.map.get_movement_cost(unit, from_hex, to_hex)
        return cost is not None and cost != float("inf")

    def can_units_attack_target_hex(self, attackers, target_hex) -> bool:
        """
        Shared land-combat hexside legality check.
        Returns False when any relevant attacking combat unit cannot legally
        project/attack across its own attacker->target hexside.
        """
        if not target_hex:
            return False

        relevant = [
            u for u in (attackers or [])
            if u.is_on_map
            and u.is_control_unit()
            and getattr(u, "transport_host", None) is None
        ]
        if not relevant:
            return False

        for unit in relevant:
            if not unit.position or None in unit.position:
                return False
            from_hex = Hex.offset_to_axial(*unit.position)
            if target_hex not in from_hex.neighbors():
                return False
            if not self.can_unit_project_across_hexside(unit, from_hex, target_hex):
                return False
        return True

    def can_control_probe_project_across_hexside(self, from_hex, to_hex, allegiance=None) -> bool:
        if not self.map:
            return False
        return self.map.can_ground_probe_cross_hexside(from_hex, to_hex)

    def _get_leader_escape_handler(self):
        if self._leader_escape_handler is None:
            self._leader_escape_handler = LeaderEscapeHandler(self)
        return self._leader_escape_handler

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
                        "movement_points": u.movement_points,
                        "river_hexside": self.map.hexside_to_tuple(getattr(u, "river_hexside", None)),
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
                                    if asset.assigned_to
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
                "territory_overrides": [
                    {"col": int(col), "row": int(row), "value": value}
                    for (col, row), value in (self.territory_overrides or {}).items()
                ],
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
        self._restore_territory_overrides(world_state.get("territory_overrides", []))
        self._analysis_cache = {}
        self._analysis_dirty = set()
        self.invalidate_overlays({"territory"})
        self.movement_service.clear_movement_undo()

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
        self.territory_overrides = {}
        self._analysis_cache = {}
        self._analysis_dirty = set()
        self._init_overlays()

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
                occupier = loc_state.get("occupier", loc.occupier)
                loc.occupier = occupier if occupier in (HL, WS, NEUTRAL) else NEUTRAL
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
            # Backward compatibility for old saves that did not serialize unit allegiance:
            # infer allegiance from the unit's country ("land") if available.
            if "allegiance" not in state:
                unit_land = getattr(unit, "land", None)
                if unit_land in self.countries:
                    unit.allegiance = self.countries[unit_land].allegiance
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
                        normalized = tuple((int(p[0]), int(p[1])) for p in river_hexside)
                        unit.river_hexside = self.map._coerce_hexside(normalized)
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

    def _restore_territory_overrides(self, overrides_state):
        self.territory_overrides = {}
        if not isinstance(overrides_state, list):
            return
        for entry in overrides_state:
            if not isinstance(entry, dict):
                continue
            try:
                col = int(entry.get("col"))
                row = int(entry.get("row"))
            except (TypeError, ValueError):
                continue
            value = entry.get("value")
            if value in (HL, WS, "contested"):
                self.territory_overrides[(col, row)] = value

    def _compute_territory_scenario_baseline(self) -> Dict[Tuple[int, int], str]:
        return board_analysis.compute_territory_scenario_baseline(self)

    def _apply_country_territory_overrides(self, values: Dict[Tuple[int, int], str]) -> Dict[Tuple[int, int], str]:
        return board_analysis.apply_country_territory_overrides(self, values)

    def compute_territory_baseline(self) -> Dict[Tuple[int, int], str]:
        return board_analysis.compute_territory_baseline(self)

    def update_territory_overrides(self):
        facts = self.get_control_facts()
        self.territory_overrides = board_analysis.compute_territory_overrides(self, control_facts=facts)

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

    def apply_conscription(self, kept_unit, discarded_unit):
        """Apply conscription result: keep one unit, destroy the other."""
        if kept_unit.is_fleet():
            # Fleet replacements become READY on the next replacements turn.
            kept_unit.status = UnitState.INACTIVE
            kept_unit.replacement_ready_turn = self.turn + 1
        else:
            kept_unit.status = UnitState.READY

        discarded_unit.status = UnitState.DESTROYED
        self.movement_service.remove_unit_from_board(
            discarded_unit,
            escaped=False,
            clear_transport=True,
            clear_river_hexside=True,
            remove_passengers=True,
        )

    def process_delayed_fleet_replacements(self):
        """
        Promotes fleets recovered by conscription to READY at the start of a later replacement turn.
        """
        for unit in self.units:
            if not unit.is_fleet():
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
        if unit.is_fleet():
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
        unit_id = TextFormatter.format_unit_log_string(unit)
        roll = random.randint(1, 10)
        result = {"roll": roll, "unit": unit}

        # 1. Sink
        if roll == 1:
            result["effect"] = "sink"
            self.damage_unit(unit, mode="destroy")
            print(f"Maelstrom Effect (Roll {roll}): Ship {unit_id} destroyed!")

        # 2-5. Stay
        elif 2 <= roll <= 5:
            result["effect"] = "stay"
            # End movement immediately
            unit.movement_points = 0
            # Ensure it is in the maelstrom hex (if passed for placement)
            if maelstrom_hex:
                self.move_unit(unit, maelstrom_hex)
            print(f"Maelstrom Effect (Roll {roll}): Ship {unit_id} trapped for the turn.")

        # 6-8. Opponent Chooses Exit
        elif 6 <= roll <= 8:
            result["effect"] = "emerge"
            result["chooser"] = "opponent"

            # Identify current location to find neighbors
            current_hex = maelstrom_hex if maelstrom_hex else Hex.offset_to_axial(*unit.position)
            result["options"] = self.map.get_maelstrom_exits(current_hex)
            print(f"Maelstrom Effect (Roll {roll}): Opponent chooses exit for {unit_id}.")

        # 9-10. Player Chooses Exit
        else: # 9, 10
            result["effect"] = "emerge"
            result["chooser"] = "player"

            current_hex = maelstrom_hex if maelstrom_hex else Hex.offset_to_axial(*unit.position)
            result["options"] = self.map.get_maelstrom_exits(current_hex)
            print(f"Maelstrom Effect (Roll {roll}): Player chooses exit for {unit_id}.")

        return result

    def process_maelstrom_start_turn(self):
        """
        Checks for ships trapped in the Maelstrom at the start of Step 5.
        """
        # Find all fleets currently located in Maelstrom hexes
        trapped_ships = []
        for unit in self.units:
            if unit.is_on_map and unit.is_fleet():
                if unit.position:
                    hex_obj = Hex.offset_to_axial(*unit.position)
                    if self.map.is_maelstrom(hex_obj):
                        trapped_ships.append((unit, hex_obj))

        # Roll for each ship belonging to the active player
        for unit, hex_obj in trapped_ships:
            if unit.allegiance == self.active_player:
                print(f"Processing Maelstrom check for trapped ship: {TextFormatter.format_unit_log_string(unit)}")
                self.resolve_maelstrom_entry(unit, hex_obj)
                # Note: The 'emerge' result requires handling by the Controller/UI
                # to prompt selection from result['options'].

    def advance_phase(self):
        return self.phase_manager.advance_phase()

    def next_turn(self):
        return self.phase_manager.next_turn()

    def on_finish_replacements_round_for_player(self, allegiance: str):
        # Preserve existing behavior: only HL replacement round triggers draconian production.
        if allegiance == HL:
            self.process_draconian_production()

    def finalize_activation_phase(self):
        # Activation bonuses are valid only during the current battle turn activation step.
        self.clear_activation_bonuses()

    def prepare_for_movement_phase(self):
        for unit in self.units:
            unit.movement_points = getattr(unit, "movement", 0)
            unit.moved_this_turn = False
            unit._healed_this_combat_turn = False

    def finalize_combat_phase(self):
        # Keep end-of-combat rule ordering identical to previous PhaseManager logic.
        self.conquest_service.resolve_end_of_combat_conquest()
        self.combat_service.clear_leader_tactical_overrides()
        self.clear_combat_bonus(self.active_player)
        for unit in self.units:
            unit.attacked_this_turn = False

    def begin_next_turn(self):
        self.turn += 1
        print(f"Battle Turn: {self.turn}")
        self.phase = GamePhase.REPLACEMENTS
        # Player that lost initiative acts first in replacements.
        self.active_player = WS if self.initiative_winner == HL else HL
        self.process_delayed_fleet_replacements()

        for unit in self.units:
            unit.movement_points = getattr(unit, "movement", 0)
            unit.attacked_this_turn = False
            unit.moved_this_turn = False
            unit._healed_this_combat_turn = False

        self.check_events()
        self.evaluate_victory_conditions()

    def resolve_supply_phase(self):
        """
        Rule 12 (advanced supply):
        - Only stacked ground armies (>1 in a hex) must trace supply.
        - If no legal path to any friendly location, one army in that stack goes to RESERVE.
        """
        supply_mode = str(getattr(self, "supply", "standard")).strip().lower()
        if supply_mode != "advanced" or not self.map:
            return []

        active = self.active_player
        friendly_locations = {
            (q, r)
            for (q, r), loc in getattr(self.map, "locations", {}).items()
            if getattr(loc, "occupier", None) == active
        }

        losses = []
        # Snapshot current hex occupancy because we may mutate unit_map as losses are applied.
        for (q, r), units in list(self.map.unit_map.items()):
            stack_armies = [
                u for u in units
                if u.is_on_map
                and u.allegiance == active
                and u.is_army()
            ]
            if len(stack_armies) <= 1:
                continue

            stack_hex = Hex(q, r)
            if self._can_trace_supply_line(stack_hex, active, stack_armies[0], friendly_locations):
                continue

            casualty = self._select_supply_attrition_unit(stack_armies)
            if casualty is None:
                continue
            if getattr(casualty, "is_on_map", False):
                self.map.remove_unit_from_spatial_map(casualty)
            casualty.status = UnitState.RESERVE
            casualty.position = (None, None)
            losses.append(casualty)

        self.finalize_board_state_change()
        return losses

    def _can_trace_supply_line(self, start_hex, allegiance, sample_unit, friendly_locations):
        if not friendly_locations:
            return False

        frontier = deque([start_hex])
        visited = {(start_hex.q, start_hex.r)}

        while frontier:
            current = frontier.popleft()
            if (current.q, current.r) in friendly_locations:
                return True

            for neighbor in current.neighbors():
                nk = (neighbor.q, neighbor.r)
                if nk in visited:
                    continue
                if not self._is_valid_supply_step(current, neighbor, allegiance, sample_unit):
                    continue
                visited.add(nk)
                frontier.append(neighbor)

        return False

    def _is_valid_supply_step(self, from_hex, to_hex, allegiance, sample_unit):
        col, row = to_hex.axial_to_offset()
        if not (0 <= col < self.map.width and 0 <= row < self.map.height):
            return False

        terrain = self.map.get_terrain(to_hex)
        if terrain in (TerrainType.OCEAN, TerrainType.MAELSTROM, TerrainType.DESERT, TerrainType.SWAMP):
            return False

        # Neutral countries block supply
        country = self.get_country_by_hex(col, row)
        if country and country.allegiance == NEUTRAL:
            return False

        hexside = self.map.get_effective_hexside(from_hex, to_hex)
        if hexside in {HexsideType.MOUNTAIN, HexsideType.DEEP_RIVER, HexsideType.SEA}:
            return False

        if self.map.has_enemy_army(to_hex, allegiance):
            return False

        # Enemy ZOC blocks trace unless the hex has a friendly counter.
        if self.map.is_adjacent_to_enemy(to_hex, sample_unit) and not self._hex_has_friendly_counter(to_hex, allegiance):
            return False

        return True

    def _hex_has_friendly_counter(self, hex_coord, allegiance):
        for unit in self.map.get_units_in_hex(hex_coord.q, hex_coord.r):
            if (
                getattr(unit, "is_leader", False) == False
                and getattr(unit, "allegiance", None) == allegiance
                and getattr(unit, "is_on_map", True)
            ):
                return True
        return False

    @staticmethod
    def _select_supply_attrition_unit(stack_armies):
        depleted = [u for u in stack_armies if getattr(getattr(u, "status", None), "name", "") == "DEPLETED"]
        if depleted:
            return min(depleted, key=lambda u: (int(getattr(u, "combat_rating", 0) or 0), str(getattr(u, "id", "")), int(getattr(u, "ordinal", 1) or 1)))
        active = [u for u in stack_armies if getattr(getattr(u, "status", None), "name", "") == "ACTIVE"]
        if active:
            return min(active, key=lambda u: (int(getattr(u, "combat_rating", 0) or 0), str(getattr(u, "id", "")), int(getattr(u, "ordinal", 1) or 1)))
        return min(
            stack_armies,
            key=lambda u: (
                0 if u.is_on_map else 1,
                int(u.combat_rating),
                str(getattr(u, "id", "")),
                int(getattr(u, "ordinal", 1) or 1),
            ),
        ) if stack_armies else None

    def check_events(self):
        return self.event_system.check_events()

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
        +1 target activation rating per owned asset in player.assets that lists `country_id`
        under bonus["diplomacy"].
        """
        if not country_id:
            return 0
        player = self.players.get(allegiance)
        if not player or not hasattr(player, "assets"):
            return 0

        country_key = str(country_id).strip().lower()
        total = 0

        for asset in (player.assets.values() or []):
            bonus = getattr(asset, "bonus", None)
            if not isinstance(bonus, dict):
                continue

            targets = bonus.get("diplomacy")
            if targets is None:
                continue
            if isinstance(targets, str):
                target_list = [targets]
            elif isinstance(targets, (list, tuple, set)):
                target_list = list(targets)
            else:
                continue

            if any(str(cid).strip().lower() == country_key for cid in target_list):
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
        self.movement_service.relocate_unit_on_board(
            fleet,
            retreat_hex,
            river_hexside=retreat_side,
            clear_escaped=False,
        )
        if hasattr(fleet, "moved_this_turn"):
            fleet.moved_this_turn = True

    def _displace_enemy_fleets_in_hex(self, invading_unit, target_hex):
        """
        If an invading unit can force fleet displacement:
        identify enemy fleets in the target hex
        and attempt to displace them to the nearest legal hex.
        If no legal hex found, eliminate the fleet.
        """
        units_in_hex = list(self.map.get_units_in_hex(target_hex.q, target_hex.r))
        enemy_fleets = [
            u for u in units_in_hex
            if (
                u is not invading_unit
                and u.is_fleet()
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
                print(f"No legal displacement hex found for fleet {fleet.id}. Fleet eliminated")
                self.damage_unit(fleet, mode="eliminate")
                continue
            self._force_move_fleet_to_state(fleet, retreat_state)

    def _force_enemy_leader_escapes_in_hex(self, invading_unit, target_hex):
        leaders = [
            u for u in list(self.map.get_units_in_hex(target_hex.q, target_hex.r))
            if (
                u is not invading_unit
                and getattr(u, "allegiance", None) not in (getattr(invading_unit, "allegiance", None), NEUTRAL, None)
                and u.is_on_map
                and u.is_leader()
            )
        ]
        if not leaders:
            return

        checks = [
            LeaderEscapeCheck(
                leader=leader,
                origin_hex=target_hex,
                roll_required=False,
                require_prior_combat_stack=False,
                skip_if_allied_combat_present=False,
                auto_place_on_success=True,
            )
            for leader in leaders
        ]
        self._get_leader_escape_handler().handle_leader_escapes(checks, auto_resolve_ai=True)

    def apply_forced_entry_displacement(self, invading_unit, target_hex):
        """Apply forced fleet displacement and leader escapes when a control unit enters a hex."""
        if not invading_unit or not invading_unit.is_control_unit():
            return
        self._displace_enemy_fleets_in_hex(invading_unit, target_hex)
        self._force_enemy_leader_escapes_in_hex(invading_unit, target_hex)

    def damage_unit(self, unit, mode: str = "deplete"):
        """
        Apply unit damage through a single model entry point.

        mode:
        - "deplete": ACTIVE -> DEPLETED, DEPLETED -> RESERVE
        - "eliminate": force RESERVE
        - "destroy": force DESTROYED
        """
        if unit is None:
            return

        was_on_map = bool(
            getattr(unit, "is_on_map", False)
            and getattr(unit, "position", None)
            and None not in unit.position
        )

        if mode == "deplete":
            unit.deplete()
        elif mode == "eliminate":
            unit.eliminate()
        elif mode == "destroy":
            unit.destroy()
        else:
            raise ValueError(f"Unsupported damage mode: {mode}")

        if was_on_map and (
            not getattr(unit, "is_on_map", False)
            or not getattr(unit, "position", None)
            or None in unit.position
        ):
            if getattr(self, "map", None):
                self.map.remove_unit_from_spatial_map(unit)

    def move_unit(
        self,
        unit,
        target_hex,
        invalidate_analysis: bool = True,
        update_territory: bool = True,
        invalidate_overlays: bool = True,
        enforce_end_terrain: bool = True,
        river_hexside=_KEEP_FIELD,
    ):
        """
        Centralizes the move: updates unit.position AND the spatial map.
        target_hex: Hex object (axial)
        """
        unit_id = TextFormatter.format_unit_log_string(unit)
        # Prevent moving units that are transported aboard a carrier
        if getattr(unit, 'transport_host', None) is not None:
            # Transported armies cannot move on their own while aboard
            print(f"Unit {unit_id} is transported aboard {unit.transport_host.id} and cannot move independently.")
            return

        # Update position and spatial map (single movement mutation path)
        offset_coords = target_hex.axial_to_offset()
        if unit.is_fleet() and river_hexside is not _KEEP_FIELD:
            self.movement_service.relocate_unit_on_board(
                unit,
                target_hex,
                river_hexside=river_hexside,
                clear_escaped=True,
            )
        else:
            self.movement_service.relocate_unit_on_board(
                unit,
                target_hex,
                clear_escaped=True,
            )

        if self.phase == GamePhase.MOVEMENT:
            unit.moved_this_turn = True

        # Rule: control units displace enemy fleets and force enemy leader escapes.
        self.apply_forced_entry_displacement(unit, target_hex)

        if invalidate_analysis and update_territory and invalidate_overlays:
            self.finalize_board_state_change()
        else:
            if invalidate_analysis:
                self.invalidate_analysis({"control_facts"})
            if update_territory:
                self.update_territory_overrides()
            if invalidate_overlays:
                self.invalidate_overlays({"control", "territory", "supply", "ws_power", "hl_power", "threat"})

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
        self.movement_service.remove_unit_from_board(
            unit,
            escaped=True,
            clear_transport=True,
            clear_river_hexside=True,
            remove_passengers=True,
        )

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

        # Update location occupiers to match new allegiance
        from src.game.map import Hex
        for loc in country.locations.values():
            loc.occupier = allegiance
            if loc.coords and hasattr(self.map, "locations"):
                hex_obj = Hex.offset_to_axial(*loc.coords)
                map_loc = self.map.locations.get((hex_obj.q, hex_obj.r))
                if map_loc and map_loc is not loc:
                    map_loc.occupier = allegiance

        self._apply_solamnic_tower_activation(country_id, previous_allegiance)

        print(f"Country {self.translator.get_country_name(country_id)} activated for {allegiance}")
        self.update_territory_overrides()
        self.invalidate_overlays({"control", "territory", "supply"})

    def is_solamnic_country_for_tower_rule(self, country_id: str) -> bool:
        country = self.countries.get(country_id)
        return bool(
            country
            and country.id != self.tower_country_id
            and self._country_has_tag(country, self.tag_knight_countries)
        )

    def get_ws_solamnic_activation_bonus(self) -> int:
        """
        +1 WS activation rating per nation controlled by HL or conquered (War is raging...)
        First 7 countries are skipped (Dragonflights and Taman Busuk).
        """
        country_list = list(self.countries.values())
        return sum(
            1
            for i, country in enumerate(country_list)
            if i >= 7 and (country.allegiance == HL)
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
        - Only friendly-occupied locations are eligible.
        """
        if allegiance not in (HL, WS):
            return False
        if not location or not location.coords:
            return False

        return location.occupier == allegiance

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


    def resolve_event(self, event):
        pass







