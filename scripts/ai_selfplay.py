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
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.content.config import LOGS_DIR, SCENARIOS_DIR
from src.content.constants import HL, WS
from src.content.loader import load_scenario_yaml
from src.content.specs import GamePhase
from src.game.ai_baseline import BaselineAIPlayer
from src.game.diplomacy import DiplomacyService
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
    activations_succeeded: int
    movement_timing_total_ms_avg: float | None = None
    movement_tactical_eval_ms_avg: float | None = None
    movement_tactical_move_units_ms_avg: float | None = None
    movement_tactical_no_op_count: int = 0
    movement_tactical_samples: int = 0


def _parse_kv_metrics(msg: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in msg.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        out[key.strip()] = value.strip().rstrip(",")
    return out


def _to_float_ms(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.removesuffix("ms"))
    except Exception:
        return None


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
    diplomacy_service = DiplomacyService(game_state)
    ai = BaselineAIPlayer(game_state, movement_service, diplomacy_service)

    movement_actions = 0
    combat_actions = 0
    activations_succeeded = 0
    movement_undo_context: tuple[int, str, GamePhase] | None = None
    movement_timing_total_ms: list[float] = []
    movement_tactical_eval_ms: list[float] = []
    movement_tactical_move_units_ms: list[float] = []
    movement_tactical_no_op_count = 0
    movement_tactical_samples = 0

    original_log = ai._log

    def _instrumented_log(msg: str):
        nonlocal movement_tactical_no_op_count, movement_tactical_samples
        if msg.startswith("movement_timing "):
            metrics = _parse_kv_metrics(msg)
            total_ms = _to_float_ms(metrics.get("total"))
            if total_ms is not None:
                movement_timing_total_ms.append(total_ms)
        elif msg.startswith("movement_tactical "):
            metrics = _parse_kv_metrics(msg)
            eval_ms = _to_float_ms(metrics.get("eval_total"))
            if eval_ms is not None:
                movement_tactical_eval_ms.append(eval_ms)
        elif msg.startswith("movement_tactical_exec "):
            movement_tactical_samples += 1
            metrics = _parse_kv_metrics(msg)
            move_units_ms = _to_float_ms(metrics.get("move_units"))
            if move_units_ms is not None:
                movement_tactical_move_units_ms.append(move_units_ms)
            if metrics.get("no_op", "").lower() == "true":
                movement_tactical_no_op_count += 1
        original_log(msg)

    ai._log = _instrumented_log

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
                event = game_state.event_system.draw_strategic_event(active_player)
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
                    if hasattr(movement_service, "clear_movement_undo"):
                        movement_service.clear_movement_undo()
                    movement_undo_context = context
                ai.assign_assets(active_player)
                moved = ai.execute_best_movement(active_player)
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
        activations_succeeded=activations_succeeded,
        movement_timing_total_ms_avg=(
            sum(movement_timing_total_ms) / len(movement_timing_total_ms)
            if movement_timing_total_ms else None
        ),
        movement_tactical_eval_ms_avg=(
            sum(movement_tactical_eval_ms) / len(movement_tactical_eval_ms)
            if movement_tactical_eval_ms else None
        ),
        movement_tactical_move_units_ms_avg=(
            sum(movement_tactical_move_units_ms) / len(movement_tactical_move_units_ms)
            if movement_tactical_move_units_ms else None
        ),
        movement_tactical_no_op_count=movement_tactical_no_op_count,
        movement_tactical_samples=movement_tactical_samples,
    )


def _build_summary(
    scenario_id: str,
    base_seed: int,
    max_ticks: int,
    supply: str,
    results: list[MatchResult],
) -> dict[str, Any]:
    def _avg(values: list[float]) -> float | None:
        return (sum(values) / len(values)) if values else None

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
    movement_total_avgs = [r.movement_timing_total_ms_avg for r in results if r.movement_timing_total_ms_avg is not None]
    movement_eval_avgs = [r.movement_tactical_eval_ms_avg for r in results if r.movement_tactical_eval_ms_avg is not None]
    movement_exec_avgs = [r.movement_tactical_move_units_ms_avg for r in results if r.movement_tactical_move_units_ms_avg is not None]
    no_op_total = sum(r.movement_tactical_no_op_count for r in results)
    no_op_samples = sum(r.movement_tactical_samples for r in results)

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
        "average_activations_succeeded": (sum(r.activations_succeeded for r in results) / total) if total else 0.0,
        "average_movement_timing_total_ms": _avg(movement_total_avgs),
        "average_movement_tactical_eval_ms": _avg(movement_eval_avgs),
        "average_movement_tactical_move_units_ms": _avg(movement_exec_avgs),
        "movement_tactical_no_op_rate": (no_op_total / no_op_samples) if no_op_samples else 0.0,
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
