import tempfile
from pathlib import Path

import yaml

from src.content.config import SCENARIOS_DIR
from src.content.constants import HL, WS
from src.content.loader import load_scenario_yaml
from src.game.game_state import GameState


def _base_campaign_data():
    scenario_path = Path(SCENARIOS_DIR) / "campaign_0_war_of_the_lance.yaml"
    with open(scenario_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_initial_setup_assets_populates_player_catalog():
    raw = _base_campaign_data()
    raw["scenario"]["initial_setup"]["highlord"]["assets"] = ["dragon_orb"]
    raw["scenario"]["initial_setup"]["highlord"].pop("artifacts", None)
    raw["scenario"]["initial_setup"]["whitestone"]["assets"] = []

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tmp:
        yaml.safe_dump(raw, tmp, sort_keys=False)
        tmp_path = tmp.name

    try:
        spec = load_scenario_yaml(tmp_path)
        assert spec.setup["highlord"]["assets"] == ["dragon_orb"]

        gs = GameState()
        gs.load_scenario(spec)
        assert "dragon_orb" in gs.players[HL].assets
        assert "dragon_orb" not in gs.players[WS].assets
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_initial_setup_artifacts_alias_still_supported():
    raw = _base_campaign_data()
    raw["scenario"]["initial_setup"]["highlord"]["artifacts"] = ["dragon_orb"]
    raw["scenario"]["initial_setup"]["highlord"].pop("assets", None)

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tmp:
        yaml.safe_dump(raw, tmp, sort_keys=False)
        tmp_path = tmp.name

    try:
        spec = load_scenario_yaml(tmp_path)
        assert spec.setup["highlord"]["assets"] == ["dragon_orb"]
        assert spec.setup["highlord"]["artifacts"] == ["dragon_orb"]

        gs = GameState()
        gs.load_scenario(spec)
        assert "dragon_orb" in gs.players[HL].assets
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_initial_setup_assets_quantity_map_supported():
    raw = _base_campaign_data()
    raw["scenario"]["initial_setup"]["highlord"]["assets"] = {"dragon_orb": 1}
    raw["scenario"]["initial_setup"]["highlord"].pop("artifacts", None)

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tmp:
        yaml.safe_dump(raw, tmp, sort_keys=False)
        tmp_path = tmp.name

    try:
        spec = load_scenario_yaml(tmp_path)
        assert "dragon_orb" in spec.setup["highlord"]["assets"]

        gs = GameState()
        gs.load_scenario(spec)
        assert "dragon_orb" in gs.players[HL].assets
    finally:
        Path(tmp_path).unlink(missing_ok=True)
