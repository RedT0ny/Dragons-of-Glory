import csv, yaml, json
import os, re
from dataclasses import asdict
from collections import defaultdict
from src.content.constants import DRAGONFLIGHTS, DIRECTION_MAP, HL, WS, NEUTRAL
from src.content.specs import *


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "item"

def _string_to_enum(value: Optional[str], enum_class) -> Optional[any]:
    """
    Converts a string value to its corresponding Enum member.
    Returns None if value is None or not found in the enum.
    """
    if not value:
        return None

    # Try direct value match (e.g., "inf" -> UnitType.INFANTRY)
    try:
        return enum_class(value.lower())
    except (ValueError, AttributeError):
        pass

    # Try name match (e.g., "infantry" -> UnitType.INFANTRY)
    try:
        return enum_class[value.upper()]
    except (KeyError, AttributeError):
        pass

    return None

def load_scenario_yaml(path: str) -> ScenarioSpec:
    """
    Loads a scenario definition from YAML and returns a structured ScenarioSpec.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    data = raw_data.get("scenario", {})
    
    # Extract setup data
    setup_raw = data.get("initial_setup", {})
    
    # We maintain the structure for players and neutral countries
    setup = {
        "neutral_countries": setup_raw.get("neutral", {}).get("countries", []),
        "highlord": setup_raw.get("highlord", {}),
        "whitestone": setup_raw.get("whitestone", {})
    }

    # Consolidated victory conditions from both players if defined at player level
    # or from a top-level victory_conditions key (like in the campaign)
    v_conds = data.get("victory_conditions", {})
    if not v_conds:
        v_conds = {
            "highlord": setup["highlord"].get("victory_conditions", {}),
            "whitestone": setup["whitestone"].get("victory_conditions", {})
        }

    return ScenarioSpec(
        id=data.get("id", "unknown"),
        description=data.get("description", ""),
        map_subset=data.get("map_subset"),
        start_turn=data.get("start_turn", 1),
        end_turn=data.get("end_turn", 30),
        initiative_start=data.get("initiative_start", "highlord"),
        active_events=data.get("active_events", []),
        setup=setup,
        victory_conditions=v_conds,
        picture=data.get("picture", "scenario.jpg"),
        notes=data.get("notes", "")
    )

def save_game_state(path: str, scenario_id: str, turn: int, phase: str, active_player: str, units: List[Dict[str, Any]], activated_countries: List[str]):
    """
    Serializes the current game state into a YAML file.
    """
    data = {
        "metadata": {
            "scenario_id": scenario_id,
            "turn": turn,
            "phase": phase,
            "active_player": active_player,
            "save_timestamp": os.path.getmtime(path) if os.path.exists(path) else None # Placeholder for actual time
        },
        "world_state": {
            "activated_countries": activated_countries,
            "units": units
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)

def load_map_config(path: str) -> MapConfigSpec:
    """
    Loads the master map configuration from YAML.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    
    data = raw.get("master_map", {})
    
    # Flatten special locations into LocationSpecs
    special_locs = []
    loc_groups = data.get("special_locations", {})
    for loc_type, loc_list in loc_groups.items():
        for loc in loc_list:
            special_locs.append(LocationSpec(
                id=loc["id"],
                loc_type=loc_type,
                coords=tuple(loc["coords"])
            ))

    return MapConfigSpec(
        name=data.get("name", "Unknown"),
        width=data.get("width", 0),
        height=data.get("height", 0),
        hex_size=data.get("hex_size", 0),
        terrain_types=data.get("terrain_types", []),
        hexsides=data.get("hexsides", {}),
        special_locations=special_locs
    )

def load_game_state(path: str) -> SaveGameSpec:
    """
    Loads a saved game file and returns a structured SaveGameSpec.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Save file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return SaveGameSpec(
        metadata=data.get("metadata", {}),
        world_state=data.get("world_state", {})
    )

def load_data(file_path):
    """
    Centralized loader to handle various data formats (YAML, CSV).
    """
    if not os.path.exists(file_path):
        print(f"Warning: File not found at {file_path}")
        return {}

    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext in ['.yaml', '.yml']:
            with open(file_path, 'r') as f:
                return yaml.safe_load(f)
        elif ext == '.csv':
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                return [row for row in reader]
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return {}

    return {}

def load_terrain_csv(path: str) -> Dict[str, str]:
    """
    Reads ansalon_map.csv (semicolon matrix format) and returns 
    a dict mapping "col,row" -> terrain_type.
    Preserves the 'c_' prefix for coastal hexes.
    """
    terrain_map = {}
    if not os.path.exists(path):
        return terrain_map

    with open(path, "r", encoding="utf-8") as f:
        # Use semicolon as the delimiter based on your CSV content
        reader = csv.reader(f, delimiter=';')
        rows = list(reader)
    
        if not rows:
            return terrain_map

        # Row 0 is the header: Qol/Row;0;1;2;...
        # Each subsequent row starts with the row index: 0;ocean;ocean;...
        for row_data in rows[1:]:
            row_idx = row_data[0]
            for col_idx, raw_terrain in enumerate(row_data[1:]):
                # Clean the terrain string
                terrain = raw_terrain.strip().lower()
            
                # Rule: Remove 'c_' prefix for visual patterns
                #if terrain.startswith("c_"):
                #    terrain = terrain[2:]

                key = f"{col_idx},{row_idx}"
                terrain_map[key] = terrain
            
    return terrain_map

def load_countries_yaml(path: str) -> Dict[str, CountrySpec]:
    """
    Returns a dictionary of country raw data specs,
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    specs = {}
    for cid, info in data.items():
        locations = [
            LocationSpec(
                id=lid,
                loc_type=linfo.get("loc_type", "city"),
                coords=tuple(linfo.get("coords", [0, 0])),
                is_capital=lid == info.get("capital_id")
            )
            for lid, linfo in info.get("locations", {}).items()
        ]

        specs[cid] = CountrySpec(
            id=cid,
            capital_id=info.get("capital_id"),
            strength=info.get("strength", 0),
            allegiance=info.get("allegiance", "neutral"),
            alignment=tuple(info.get("alignment", [0, 0])),
            color=info.get("color", "#00000000"),
            locations=locations,
            territories=[tuple(t) for t in info.get("territories", [])]
        )
    return specs

def load_special_locations(path: str) -> List[LocationSpec]:
    """
    Loads neutral/special locations grouped by type from map_config.yaml.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Access the grouped dictionary from map_config.yaml
    special_data = data.get("master_map", {}).get("special_locations", {})
    specs = []

    for loc_type, locations in special_data.items():
        for loc_info in locations:
            specs.append(LocationSpec(
                id=loc_info["id"],
                loc_type=loc_type,
                coords=tuple(loc_info["coords"])
            ))
    return specs

def load_hexsides(grid, hexside_list):
    for entry in hexside_list:
        # entry format: [col, row, direction_str, type]
        col, row, direction_str, side_type = entry
        dir_idx = DIRECTION_MAP[direction_str]
        grid.add_hexside_by_offset(col, row, dir_idx, side_type)

def parse_units_csv(path: str) -> List[UnitSpec]:
    specs = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        unnamed_counters = {}
        for row in reader:
            # Helper to extract and clean
            get_val = lambda k: (row.get(k) or "").strip() or None
            get_int = lambda k: int(row[k]) if row.get(k) and row[k].isdigit() else None

            land = get_val("land")
            df = land.lower() if land and land.lower() in DRAGONFLIGHTS else None
            country = None if df else land
            

            u_type = get_val("type")
            race = get_val("race")

            # ID generation
            csv_id = get_val("id")
                
            if csv_id:
                # If CSV provides an ID, use it! (e.g. 'lord_soth')
                base_id = _slugify(csv_id)
            else:
                # Use 'no_land' or similar if land is missing to keep IDs clean
                land_key = _slugify(land) if land else ""
                base_key = f"{land_key}_{race or 'r'}_{u_type or 'u'}"
                base_id = f"{base_key}"

            specs.append(UnitSpec(
                id=base_id, # This is now GUARANTEED to be a string
                unit_type=u_type, race=race,
                country=country, dragonflight=df, 
                allegiance=(get_val("allegiance") or "") or None,
                terrain_affinity=get_val("terrain_affinity"),
                combat_rating=get_int("combat_rating"),
                tactical_rating=get_int("tactical_rating"),
                movement=get_int("movement"),
                quantity=get_int("quantity") or 1
            ))
    return specs

def resolve_scenario_units(spec: ScenarioSpec, units_csv_path: str) -> List[UnitSpec]:
    #Avoid crashing if no scenario is passed as argument
    if spec is None: return []

    # 1. Expand all unit specs from CSV
    raw_specs = parse_units_csv(units_csv_path)
    all_counters = []
    for s in raw_specs:
        for i in range(1, s.quantity + 1):
            # Create a unique copy for every single counter
            new_id = f"{s.id}_{i}" if s.quantity > 1 else s.id
            new_spec = UnitSpec(**{**asdict(s), "id": new_id, "quantity": 1, "ordinal": i})
            all_counters.append(new_spec)

    # 2. Index for lookup
    idx = {
        "id": {u.id: u for u in all_counters},
        "country": defaultdict(list),
        "type": defaultdict(list),
        "race": defaultdict(list),
        "df": defaultdict(list)
    }
    for u in sorted(all_counters, key=lambda x: x.id):
        if u.country: idx["country"][u.country.lower()].append(u)
        if u.unit_type: idx["type"][u.unit_type.lower()].append(u)
        if u.race: idx["race"][u.race.lower()].append(u)
        if u.dragonflight: idx["df"][u.dragonflight.lower()].append(u)

    # 3. Filter based on ScenarioSpec
    selected_specs = []
    for allegiance in [HL, WS]:
        p_cfg = spec.setup.get(allegiance, {})

        # Process countries
        for cname, config in p_cfg.get("countries", {}).items():
            lc = cname.lower()

            # Case 1: "units: all" - Get all units from this country
            if config == "all" or (isinstance(config, dict) and config.get("units") == "all"):
                # Try country first
                matching_units = idx["country"].get(lc, [])

                # If no country match, try dragonflight
                if not matching_units:
                    matching_units = idx["df"].get(lc, [])

                for unit_spec in matching_units:
                    unit_spec.allegiance = allegiance  # Modify in-place
                    selected_specs.append(unit_spec)

            # Case 2: "units_by_type" - Get specific types/races with quantities
            elif isinstance(config, dict) and "units_by_type" in config:
                units_by_type = config["units_by_type"]

                for type_or_race, type_config in units_by_type.items():
                    # Support for simplified format: "inf: 4" instead of "inf: { quantity: 4 }"
                    if isinstance(type_config, int):
                        requested_qty = type_config
                    else:
                        requested_qty = 1

                    # Try to find units matching this type or race from this country/dragonflight
                    matching_units = []

                    # First check if it's a unit type (e.g., "fleet", "admiral")
                    if type_or_race_lower in idx["type"]:
                        matching_units = [u for u in idx["type"][type_or_race_lower]
                                          if (u.country and u.country.lower() == lc) or
                                          (u.dragonflight and u.dragonflight.lower() == lc)]

                    # Then check if it's a race (e.g., "minotaur")
                    if not matching_units and type_or_race_lower in idx["race"]:
                        matching_units = [u for u in idx["race"][type_or_race_lower]
                                          if (u.country and u.country.lower() == lc) or
                                          (u.dragonflight and u.dragonflight.lower() == lc)]

                    # Take only the requested quantity
                    for unit_spec in matching_units[:requested_qty]:
                        unit_spec.allegiance = allegiance
                        selected_specs.append(unit_spec)

        # Process explicit units (heroes, wizards, etc.)

        for uid in p_cfg.get("explicit_units", []):
            u = idx["id"].get(uid.lower())
            if u:
                u.allegiance = allegiance  # Modify in-place
                selected_specs.append(u)

    return selected_specs

def resolve_scenario_countries(spec: ScenarioSpec, countries_yaml_path: str) -> Dict[str, CountrySpec]:
    """
    Loads country specs and filters/configures them based on the ScenarioSpec.
    Sets the allegiance correctly for Highlord, Whitestone, and Neutral countries.
    """
    if spec is None: return {}

    # 1. Load all raw country specs
    all_specs = load_countries_yaml(countries_yaml_path)
    resolved_specs = {}

    def _process_group(group_data, allegiance):
        """Helper to extract country IDs and set allegiance."""
        if not group_data: return

        # Handle list (names only) or dict (names with config)
        c_ids = group_data.keys() if isinstance(group_data, dict) else group_data

        for cid in c_ids:
            if cid in all_specs:
                c_spec = all_specs[cid]
                c_spec.allegiance = allegiance
                resolved_specs[cid] = c_spec

    # 2. Process Highlord
    hl_setup = spec.setup.get("highlord", {})
    _process_group(hl_setup.get("countries", {}), HL)

    # 3. Process Whitestone
    ws_setup = spec.setup.get("whitestone", {})
    _process_group(ws_setup.get("countries", {}), WS)

    # 4. Process Neutrals
    # Note: load_scenario_yaml maps the neutral section to "neutral_countries"
    neutral_data = spec.setup.get("neutral_countries", [])
    _process_group(neutral_data, NEUTRAL)

    return resolved_specs

def load_artifacts_yaml(path: str) -> Dict[str, ArtifactSpec]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    specs = {}
    for aid, info in data.items():
        specs[aid] = ArtifactSpec(
            id=aid,
            description=info.get("description", ""),
            bonus=info.get("bonus", {}),
            requirements=info.get("requirements", []),
            is_consumable=info.get("is_consumable", False)
        )
    return specs

def load_events_yaml(path: str) -> Dict[str, EventSpec]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    specs = {}
    for eid, info in data.items():
        specs[eid] = EventSpec(
            id=eid,
            event_type=info.get("type", "bonus"),
            description=info.get("description", ""),
            trigger_conditions=info.get("trigger", {}),
            effects=info.get("effects", {}),
            allegiance=info.get("allegiance")
        )
    return specs
