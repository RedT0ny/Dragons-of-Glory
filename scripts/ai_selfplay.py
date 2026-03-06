import argparse
import io
import json
import random
import sys
from contextlib import nullcontext, redirect_stdout
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

# Ensure imports work when executing `python scripts/ai_selfplay.py`.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.content.config import LOGS_DIR, SCENARIOS_DIR
from src.content.constants import HL, WS
from src.content.loader import load_scenario_yaml
from src.content.specs import GamePhase
from src.game.ai_baseline import BaselineAIPlayer
from src.game.diplomacy import DiplomacyActivationService
from src.game.game_state import GameState
from src.game.movement import MovementService


def _disable_combat_popups():
    # Headless mode: prevent Qt dialogs during movement interceptions/combat.
    import src.game.ai_baseline as ai_baseline_module
    import src.game.movement as movement_module

    ai_baseline_module.show_combat_result_popup = lambda *args, **kwargs: None
    movement_module.show_combat_result_popup = lambda *args, **kwargs: None


def _resolve_scenario(scenario_arg: str | None):
    if scenario_arg:
        candidate = Path(scenario_arg)
        if candidate.exists():
            return load_scenario_yaml(str(candidate))

        scenarios_dir = Path(SCENARIOS_DIR)
        for path in sorted(scenarios_dir.glob("*.yaml")):
            spec = load_scenario_yaml(str(path))
            if spec.id == scenario_arg:
                return spec
        raise ValueError(f"Scenario not found by path or id: {scenario_arg}")

    scenarios_dir = Path(SCENARIOS_DIR)
    scenario_files = sorted(scenarios_dir.glob("*.yaml"))
    if not scenario_files:
        raise ValueError(f"No scenario files found in {SCENARIOS_DIR}")
    return load_scenario_yaml(str(scenario_files[0]))


@dataclass
class MatchResult:
    game_index: int
    seed: int
    completed: bool
    winner: str | None
    reason: str
    turns: int
    ticks: int
    final_phase: str
    active_player: str
    victory_points: dict[str, int]
    movement_actions: int
    combat_actions: int
    invasions_attempted: int
    invasions_succeeded: int
    activations_succeeded: int


def _run_one_game(
    scenario_spec,
    seed: int,
    game_index: int,
    max_ticks: int,
    supply: str,
    quiet: bool,
) -> MatchResult:
    random.seed(seed)

    game_state = GameState()
    game_state.load_scenario(scenario_spec)
    game_state.supply = supply
    if HL in game_state.players:
        game_state.players[HL].set_ai(True)
    if WS in game_state.players:
        game_state.players[WS].set_ai(True)

    movement_service = MovementService(game_state)
    diplomacy_service = DiplomacyActivationService(game_state)
    ai = BaselineAIPlayer(game_state, movement_service, diplomacy_service)

    movement_actions = 0
    combat_actions = 0
    invasions_attempted = 0
    invasions_succeeded = 0
    activations_succeeded = 0
    movement_undo_context: tuple[int, str, GamePhase] | None = None

    def attempt_invasion(country_id: str):
        nonlocal invasions_attempted, invasions_succeeded
        invasions_attempted += 1
        invasion_data = movement_service.get_invasion_force(country_id)
        outcome = diplomacy_service.resolve_invasion(country_id, invasion_data)
        if outcome.success and outcome.winner:
            invasions_succeeded += 1
            # New checkpoint like controller behavior.
            game_state.clear_movement_undo()
            ai.deploy_all_ready_units(
                outcome.winner,
                allow_territory_wide=True,
                country_filter=country_id,
                invasion_deployment_active=True,
                invasion_deployment_allegiance=outcome.winner,
                invasion_deployment_country_id=country_id,
            )

    stdout_ctx = redirect_stdout(io.StringIO()) if quiet else nullcontext()
    ticks = 0
    with stdout_ctx:
        while not game_state.game_over and ticks < max_ticks:
            ticks += 1
            current_phase = game_state.phase
            active_player = game_state.active_player

            if current_phase == GamePhase.DEPLOYMENT:
                ai.deploy_all_ready_units(active_player)
                game_state.advance_phase()
                continue

            if current_phase == GamePhase.REPLACEMENTS:
                ai.process_replacements(active_player)
                game_state.advance_phase()
                continue

            if current_phase == GamePhase.STRATEGIC_EVENTS:
                event = game_state.draw_strategic_event(active_player)
                if event:
                    event.force_activate(game_state)
                ai.assign_assets(active_player)
                game_state.advance_phase()
                continue

            if current_phase == GamePhase.ACTIVATION:
                if game_state.has_neutral_countries():
                    success, _country_id = ai.perform_activation(active_player)
                    if success:
                        activations_succeeded += 1
                game_state.advance_phase()
                continue

            if current_phase == GamePhase.INITIATIVE:
                hl_roll = random.randint(1, 4)
                ws_roll = random.randint(1, 4)
                if hl_roll == ws_roll:
                    winner = game_state.initiative_winner
                elif hl_roll > ws_roll:
                    winner = HL
                else:
                    winner = WS
                game_state.set_initiative(winner)
                game_state.advance_phase()
                continue

            if current_phase == GamePhase.MOVEMENT:
                context = (game_state.turn, active_player, current_phase)
                if movement_undo_context != context:
                    game_state.clear_movement_undo()
                    movement_undo_context = context
                ai.assign_assets(active_player)
                moved = ai.execute_best_movement(active_player, attempt_invasion=attempt_invasion)
                if moved:
                    movement_actions += 1
                else:
                    game_state.advance_phase()
                continue

            if current_phase == GamePhase.COMBAT:
                fought = ai.execute_best_combat(active_player)
                if fought:
                    combat_actions += 1
                else:
                    game_state.advance_phase()
                continue

            # Covers SUPPLY and any future phase extensions.
            game_state.advance_phase()

    completed = bool(game_state.game_over)
    return MatchResult(
        game_index=game_index,
        seed=seed,
        completed=completed,
        winner=game_state.winner if completed else None,
        reason=game_state.victory_reason if completed else "max_ticks_reached",
        turns=int(game_state.turn),
        ticks=ticks,
        final_phase=game_state.phase.name if hasattr(game_state.phase, "name") else str(game_state.phase),
        active_player=str(game_state.active_player),
        victory_points=dict(getattr(game_state, "victory_points", {}) or {}),
        movement_actions=movement_actions,
        combat_actions=combat_actions,
        invasions_attempted=invasions_attempted,
        invasions_succeeded=invasions_succeeded,
        activations_succeeded=activations_succeeded,
    )


def _build_summary(
    scenario_id: str,
    base_seed: int,
    max_ticks: int,
    supply: str,
    results: list[MatchResult],
) -> dict[str, Any]:
    total = len(results)
    completed = [r for r in results if r.completed]
    timeouts = total - len(completed)
    wins = {HL: 0, WS: 0, "draw": 0}
    for r in completed:
        if r.winner in (HL, WS):
            wins[r.winner] += 1
        else:
            wins["draw"] += 1

    avg_turns = (sum(r.turns for r in completed) / len(completed)) if completed else None
    avg_ticks = (sum(r.ticks for r in results) / len(results)) if results else 0.0

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scenario_id": scenario_id,
        "games": total,
        "base_seed": base_seed,
        "max_ticks": max_ticks,
        "supply": supply,
        "completed_games": len(completed),
        "timed_out_games": timeouts,
        "wins": wins,
        "win_rate": {
            HL: (wins[HL] / total) if total else 0.0,
            WS: (wins[WS] / total) if total else 0.0,
            "draw": (wins["draw"] / total) if total else 0.0,
        },
        "average_turns_completed_games": avg_turns,
        "average_ticks_all_games": avg_ticks,
        "average_movement_actions": (sum(r.movement_actions for r in results) / total) if total else 0.0,
        "average_combat_actions": (sum(r.combat_actions for r in results) / total) if total else 0.0,
        "average_invasions_attempted": (sum(r.invasions_attempted for r in results) / total) if total else 0.0,
        "average_invasions_succeeded": (sum(r.invasions_succeeded for r in results) / total) if total else 0.0,
        "average_activations_succeeded": (sum(r.activations_succeeded for r in results) / total) if total else 0.0,
        "results": [asdict(r) for r in results],
    }


def main():
    parser = argparse.ArgumentParser(description="Run seeded AI-vs-AI self-play and write summary to logs.")
    parser.add_argument("--scenario", default=None, help="Scenario id (from data/scenarios/*.yaml) or explicit yaml path.")
    parser.add_argument("--games", type=int, default=20, help="Number of games to run.")
    parser.add_argument("--seed", type=int, default=1, help="Base random seed. Game i uses seed+i.")
    parser.add_argument("--max-ticks", type=int, default=25000, help="Safety cap on loop iterations per game.")
    parser.add_argument("--supply", choices=["standard", "advanced"], default="standard", help="Supply mode.")
    parser.add_argument("--quiet", action="store_true", help="Suppress internal engine prints during match simulation.")
    parser.add_argument("--out", default=None, help="Output summary json path. Defaults to logs/ai_selfplay_summary_<ts>.json")
    args = parser.parse_args()

    if args.games <= 0:
        raise ValueError("--games must be > 0")
    if args.max_ticks <= 0:
        raise ValueError("--max-ticks must be > 0")

    _disable_combat_popups()
    scenario_spec = _resolve_scenario(args.scenario)

    results = []
    for i in range(args.games):
        game_seed = args.seed + i
        result = _run_one_game(
            scenario_spec=scenario_spec,
            seed=game_seed,
            game_index=i + 1,
            max_ticks=args.max_ticks,
            supply=args.supply,
            quiet=args.quiet,
        )
        results.append(result)
        status = "completed" if result.completed else "timeout"
        print(
            f"[{i + 1}/{args.games}] seed={game_seed} {status} "
            f"winner={result.winner or '-'} turns={result.turns} ticks={result.ticks}"
        )

    summary = _build_summary(
        scenario_id=scenario_spec.id,
        base_seed=args.seed,
        max_ticks=args.max_ticks,
        supply=args.supply,
        results=results,
    )

    logs_dir = Path(LOGS_DIR)
    logs_dir.mkdir(parents=True, exist_ok=True)
    if args.out:
        out_path = Path(args.out)
    else:
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        out_path = logs_dir / f"ai_selfplay_summary_{scenario_spec.id}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Summary written to: {out_path}")


if __name__ == "__main__":
    main()
