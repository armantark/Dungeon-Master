from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Final

from dungeon_master.config import LLMConfig
from dungeon_master.llm.narration import NarrativeEngine
from dungeon_master.llm.planning import TurnRouter
from tools.eval_harness import (
    EVAL_DATA_PATH,
    EVAL_USER_INPUTS,
    EvalBaselineRecord,
    eval_case_for,
    eval_llm_config,
    load_baseline,
    sample_eval_state,
    write_baseline,
)

DEFAULT_PRE_COMPRESSION_REF: Final = "c209252"


def main() -> None:
    args = _parse_args()
    if args.from_ref:
        _generate_from_ref(args.from_ref, args.output)
        return

    _generate_current_baseline(args.output)


def _generate_current_baseline(output_path: Path) -> None:
    config = eval_llm_config(LLMConfig.from_env())
    if not config.is_usable():
        msg = (
            "Cannot generate DeepEval baseline without a usable LLM config. "
            "Configure the same provider credentials used by the app."
        )
        raise RuntimeError(msg)

    router = TurnRouter(config=config)
    narrator = NarrativeEngine(config=config)
    baseline = load_baseline(output_path) or {}

    for user_input in EVAL_USER_INPUTS:
        if user_input in baseline:
            continue
        state = sample_eval_state()
        case = eval_case_for(user_input)
        plan = router.plan(text=user_input)
        narration = narrator.generate(
            state=state,
            player_input=case.user_input,
            outcome=case.outcome,
            execution_context=case.execution_context,
        )
        baseline[user_input] = EvalBaselineRecord(
            route=plan.route.value,
            target_name=next(
                (op.target_name for op in reversed(plan.ops) if op.target_name is not None),
                None,
            ),
            routed_text=plan.text,
            narration=narration,
        )
        write_baseline(baseline, output_path)


def _generate_from_ref(ref: str, output_path: Path) -> None:
    repo_root = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="dm-eval-worktree-") as tmp:
        worktree = Path(tmp) / "repo"
        _run(["git", "worktree", "add", "--detach", str(worktree), ref], cwd=repo_root)
        try:
            script_path = worktree / ".tmp_generate_eval_baseline.py"
            script_path.write_text(_LEGACY_GENERATOR_SCRIPT, encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(worktree / "src")
            resolved_output = (repo_root / output_path).resolve()
            _run(
                [sys.executable, str(script_path), "--output", str(resolved_output)],
                cwd=worktree,
                env=env,
            )
        finally:
            _run(["git", "worktree", "remove", "--force", str(worktree)], cwd=repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate validated LLM baselines for DeepEval prompt drift tests.",
    )
    parser.add_argument(
        "--from-ref",
        nargs="?",
        const=DEFAULT_PRE_COMPRESSION_REF,
        help=(
            "Generate from an isolated git worktree at REF. "
            f"Defaults to {DEFAULT_PRE_COMPRESSION_REF} when passed without a value."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EVAL_DATA_PATH,
        help=f"Baseline JSON output path. Defaults to {EVAL_DATA_PATH}.",
    )
    return parser.parse_args()


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    if command[0] == "git" and command[1:3] == ["worktree", "add"]:
        worktree_path = Path(command[-2])
        if worktree_path.exists():
            shutil.rmtree(worktree_path)
    subprocess.run(command, cwd=cwd, env=env, check=True)  # noqa: S603


_LEGACY_GENERATOR_SCRIPT = textwrap.dedent(
    r"""
    from __future__ import annotations

    import argparse
    import json
    from dataclasses import replace
    from pathlib import Path

    from dungeon_master.config import LLMConfig
    from dungeon_master.domain.models import GameState, OracleKind, OracleOutcome, OracleTables
    from dungeon_master.llm.narration import NarrativeEngine
    from dungeon_master.llm.planning import TurnRouter

    EVAL_USER_INPUTS = (
        "I swing my sword at the goblin.",
        "I look around the room for traps.",
        "I try to talk my way past the guard.",
    )


    def main() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        config = replace(LLMConfig.from_env(), temperature=0.2)
        if not config.is_usable():
            raise RuntimeError("Cannot generate baseline without usable LLM config.")
        baseline = _load(args.output)
        router = TurnRouter(config=config)
        narrator = NarrativeEngine(config=config)
        for user_input in EVAL_USER_INPUTS:
            if user_input in baseline:
                continue
            state = _sample_eval_state()
            routed = router.route(text=user_input)
            outcome = OracleOutcome(
                kind=OracleKind.PLAYER_ACTION,
                question=f"Does the player succeed at: {user_input}?",
                summary="Success",
                chaos_factor=5,
            )
            narration = narrator.generate(
                state=state,
                player_input=user_input,
                outcome=outcome,
                execution_context="Steps executed successfully.",
            )
            baseline[user_input] = {
                "route": routed.route.value,
                "target_name": routed.target_name,
                "routed_text": routed.text,
                "narration": narration,
            }
            _write(args.output, baseline)


    def _load(path: Path) -> dict[str, dict[str, object]]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return payload


    def _write(path: Path, payload: dict[str, dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


    def _sample_eval_state() -> GameState:
        return GameState(
            current_scene="A dark dungeon room.",
            setting_notes="A compact dungeon used for prompt drift evaluation.",
            player_notes="A cautious adventurer with a sword.",
            oracle_tables=OracleTables(
                event_focus=[
                    "NPC action",
                    "New NPC",
                    "Move toward thread",
                    "Move away from thread",
                    "Close thread",
                    "Ambiguous event",
                ],
                event_actions=[
                    "attack",
                    "reveal",
                    "betray",
                    "pursue",
                    "hide",
                    "break",
                    "guard",
                    "signal",
                ],
                event_tones=[
                    "grim",
                    "quiet",
                    "urgent",
                    "strange",
                    "tense",
                    "hopeful",
                    "cold",
                    "bright",
                ],
                event_subjects=[
                    "goblin",
                    "door",
                    "torch",
                    "guard",
                    "trap",
                    "altar",
                    "coin",
                    "blade",
                ],
            ),
        )


    if __name__ == "__main__":
        main()
    """,
)


if __name__ == "__main__":
    main()
