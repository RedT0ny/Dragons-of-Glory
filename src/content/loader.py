import csv, yaml, json
import os, re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

DRAGONFLIGHTS = {"red", "blue", "green", "black", "white"}

@dataclass
class LocationSpec:
    id: str
    loc_type: str
    coords: Tuple[int, int]
    name: Optional[str] = None

@dataclass
class CountrySpec:
    id: str
    capital_id: str
    strength: int
    allegiance: str
    alignment: Tuple[int, int]
    color: str
    locations: List[LocationSpec]
    territories: List[Tuple[int, int]]

@dataclass
class UnitSpec:
    id: str             # The only ID we need (from CSV or generated)
    unit_type: Optional[str]
    race: Optional[str]
    country: Optional[str]
    dragonflight: Optional[str]
    allegiance: Optional[str]
    terrain_affinity: Optional[str]
    combat_rating: Optional[int]
    tactical_rating: Optional[int]
    movement: Optional[int]
    quantity: int = 1
    ordinal: int = 1
    status: str = "inactive"

def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "item"

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

def load_countries_yaml(path: str) -> Dict[str, CountrySpec]:
    """
    Returns a dictionary of raw data specs,
    not game objects.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    specs = {}
    for cid, info in data.items():
        locations = [
            LocationSpec(id=lid, **linfo)
            for lid, linfo in info.get("locations", {}).items()
        ]

        specs[cid] = CountrySpec(
            id=cid,
            capital_id=info.get("capital_id"),
            strength=info.get("strength", 0),
            allegiance=info.get("allegiance", "neutral"),
            alignment=tuple(info.get("alignment", [0, 0])),
            color=info.get("color"),
            locations=locations,
            territories=[tuple(t) for t in info.get("territories", [])]
        )
    return specs

def parse_units_csv(path: str) -> List[UnitSpec]:
    specs = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        unnamed_counters = {}
        for row in reader:
            # Helper to extract and clean
            get_val = lambda k: (row.get(k) or "").strip() or None
            get_int = lambda k: int(row[k]) if row.get(k) and row[k].isdigit() else None

            land = get_val("land")
            df = land.lower() if land and land.lower() in DRAGONFLIGHTS else None
            country = None if df else land
            
            name = get_val("name")
            u_type = get_val("type")
            race = get_val("race")

            # ID generation
            csv_id = get_val("id")
                
            if csv_id:
                # If CSV provides an ID, use it! (e.g. 'lord_soth')
                base_id = _slugify(csv_id)
            else:
                # Use 'no_land' or similar if land is missing to keep IDs clean
                land_key = _slugify(land) if land else "no_land"
                base_key = f"{u_type or 'u'}_{race or 'r'}_{land_key}"
                unnamed_counters[base_key] = unnamed_counters.get(base_key, 0) + 1
                base_id = f"{base_key}_{unnamed_counters[base_key]}"

            specs.append(UnitSpec(
                id=base_id, # This is now GUARANTEED to be a string
                name=name, unit_type=u_type, race=race,
                country=country, dragonflight=df, 
                allegiance=(get_val("allegiance") or "").title() or None,
                terrain_affinity=get_val("terrain_affinity"),
                combat_rating=get_int("combat_rating"),
                tactical_rating=get_int("tactical_rating"),
                movement=get_int("movement"),
                quantity=get_int("quantity") or 1
            ))
    return specs

def resolve_scenario_units(scenario_path: str, units_csv_path: str) -> List[UnitSpec]:
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
        "name": {u.name.lower(): u for u in all_counters if u.name},
        "country": defaultdict(list),
        "type": defaultdict(list),
        "df": defaultdict(list)
    }
    for u in sorted(all_counters, key=lambda x: x.id):
        if u.country: idx["country"][u.country.lower()].append(u)
        if u.unit_type: idx["type"][u.unit_type.lower()].append(u)
        if u.dragonflight: idx["df"][u.dragonflight.lower()].append(u)

    # 3. Process Scenario
    with open(scenario_path, "r", encoding="utf-8") as f:
        sc = yaml.safe_load(f)

    selected = []
    players = sc.get("scenario", {}).get("players", {})
    for _, p_cfg in players.items():
        # Handle Countries
        for cname, rules in p_cfg.get("countries", {}).items():
            lc = cname.lower()
            if rules.get("units_by_country") == "all":
                selected.extend(idx["country"][lc])
            
            # Unit type picking (e.g. 4 inf, 1 cav)
            for utype, uinfo in rules.get("units_by_type", {}).items():
                qty = int(uinfo.get("quantity", 0))
                # Check if this is a dragonflight color or a regular country
                candidates = idx["df"][lc] if lc in DRAGONFLIGHTS else \
                             [u for u in idx["country"][lc] if u.unit_type and u.unit_type.lower() == utype.lower()]
                selected.extend(candidates[:qty])

        # Handle Explicit picks
        for item in (p_cfg.get("explicit_units") or []):
            key = str(item).lower()
            if key in idx["id"]: selected.append(idx["id"][key])
            elif key in idx["name"]: selected.append(idx["name"][key])

    # 4. Finalize
    unique_units = []
    seen = set()
    for u in selected:
        if u.id not in seen:
            u.status = "active"
            unique_units.append(u)
            seen.add(u.id)
    return unique_units
