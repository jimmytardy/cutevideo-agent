"""Production locale d'un Short, sans base de données.

    python -m studio.run "Pourquoi les flamants roses sont roses" [--duration 45]
    python -m studio.run "…" --interactive     # ouvre Claude Code dans le run dir
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from studio.contracts import Brief, StudioResult, load_contract
from studio.launcher import (
    LaunchConfig,
    permission_args,
    build_env,
    default_runs_dir,
    prepare_run_dir,
    run_claude,
)


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:48] or "video"


def _describe_tool(data: dict[str, Any]) -> str:
    tool_input = data.get("input") or {}
    if data["name"] == "Bash":
        return str(tool_input.get("command", ""))[:140]
    return str(tool_input.get("file_path") or tool_input.get("pattern") or "")[:140]


async def _print_event(kind: str, data: dict[str, Any]) -> None:
    stamp = time.strftime("%H:%M:%S")
    if kind == "agent_start":
        print(f"{stamp} ▶ {data['role']:<12} {data.get('description', '')}", flush=True)
    elif kind == "agent_end":
        status = "✗" if data["is_error"] else "✓"
        summary = " ".join(data["output"].split())[:160]
        print(f"{stamp} {status} {data['role']:<12} {summary}", flush=True)
    elif kind == "tool":
        print(f"{stamp}   · {data['role']:<12} {data['name']}: {_describe_tool(data)}", flush=True)
    elif kind == "denied":
        print(f"{stamp}   ⊘ {data['role']:<12} {data['name']} refusé", flush=True)
    elif kind == "result":
        cost = data.get("total_cost_usd")
        print(f"{stamp} ■ fin ({data.get('num_turns')} tours"
              + (f", ${cost:.2f}" if isinstance(cost, (int, float)) else "") + ")", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m studio.run", description=__doc__)
    parser.add_argument("theme", help="sujet de la vidéo")
    parser.add_argument("--duration", type=int, default=45, help="durée cible (s)")
    parser.add_argument("--niche", default="", help="ligne éditoriale de la chaîne")
    parser.add_argument("--angle", default="")
    parser.add_argument("--language", default="fr")
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=80)
    parser.add_argument("--voice", default="")
    parser.add_argument("--run-dir", type=Path, help=f"défaut : {default_runs_dir()}/<date>-<slug>")
    parser.add_argument("--model", help="modèle Claude (défaut CLAUDE_STUDIO_MODEL ou claude-opus-5-5)")
    parser.add_argument("--interactive", action="store_true", help="ouvre Claude Code au lieu du mode headless")
    args = parser.parse_args(argv)

    brief = Brief(
        theme=args.theme,
        niche=args.niche,
        angle=args.angle,
        language=args.language,
        target_duration_s=args.duration,
        voice=args.voice,
        max_iterations=args.max_iterations,
        min_score=args.min_score,
    )
    run_dir = args.run_dir or default_runs_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(args.theme)}"
    run_dir = prepare_run_dir(run_dir, brief)
    print(f"Run dir : {run_dir}", flush=True)

    cfg = LaunchConfig()
    if args.model:
        cfg.model = args.model

    if args.interactive:
        os.chdir(run_dir)
        os.execvpe(cfg.claude_bin, [cfg.claude_bin, "/make-video", "--model", cfg.model, *permission_args()], build_env(run_dir))

    async def _session() -> None:
        # SIGTERM → annulation → run_claude tue proprement le process `claude`.
        task = asyncio.current_task()
        assert task is not None
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        await run_claude(run_dir, cfg=cfg, on_event=_print_event)

    try:
        asyncio.run(_session())
        result = load_contract(run_dir / "result.json", StudioResult)
    except (Exception, asyncio.CancelledError) as exc:
        print(f"Échec : {exc or type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    if result.final_video:
        print(f"Vidéo : {run_dir / result.final_video}")
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
