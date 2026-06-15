from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent.agents.scenario_agent import _format_research_block
from agent.core.base_agent import BaseAgent
from agent.core.database import AsyncSessionFactory, Scenario

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

FACT_CHECK_SYSTEM = """Tu es un vérificateur factuel expert pour des vidéos éducatives.
Compare le scénario à la fiche de recherche. Signale uniquement les erreurs vérifiables.
Retourne UNIQUEMENT du JSON valide."""

FACT_CHECK_PROMPT = """Vérifie la précision factuelle du scénario.

SUJET : {theme}

{research_block}

SCÉNARIO ({segment_count} segments) :
{scenario_json}

Retourne UNIQUEMENT ce JSON :
{{
  "passed": true,
  "errors": [
    {{"segment_order": 1, "claim": "...", "issue": "...", "severity": "major|minor"}}
  ],
  "warnings": [
    {{"segment_order": 1, "claim": "...", "issue": "...", "severity": "minor"}}
  ],
  "start_from": "scenario_agent"
}}

Règles :
- passed=false si au moins une erreur severity=major
- start_from = research_agent si le brief est insuffisant, scenario_agent si le scénario déforme les faits
- Ne signale pas d'opinions, seulement faits/dates/noms/chiffres"""


@dataclass
class FactCheckResult:
    passed: bool
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    start_from: str

    def has_major_errors(self) -> bool:
        return any(e.get("severity") == "major" for e in self.errors)


class FactCheckerAgent(BaseAgent):
    """Vérifie scénario vs research brief avant étapes coûteuses."""

    name = "fact_checker_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> FactCheckResult:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id,
            {"scenario_id": str(scenario.id)},
            iteration=ctx.iteration,
        )
        try:
            result = await self._check(ctx, scenario)
            await self.end_run(run, {
                "passed": result.passed,
                "errors_count": len(result.errors),
                "warnings_count": len(result.warnings),
                "errors": result.errors,
                "warnings": result.warnings,
                "start_from": result.start_from,
            })
            return result
        except Exception as exc:
            await self.fail_run(run, exc)
            raise

    async def _check(self, ctx: "PipelineContext", scenario: Scenario) -> FactCheckResult:
        segments = scenario.segments or []
        if not ctx.research_brief:
            logger.warning("Fact check sans research brief — passage automatique")
            return FactCheckResult(passed=True, errors=[], warnings=[], start_from="scenario_agent")

        prompt = FACT_CHECK_PROMPT.format(
            theme=ctx.theme,
            research_block=_format_research_block(ctx.research_brief),
            segment_count=len(segments),
            scenario_json=json.dumps({"segments": segments}, ensure_ascii=False, indent=2),
        )
        raw = await self._call_claude(prompt, system=FACT_CHECK_SYSTEM, max_tokens=4096)
        data = self._parse_json(raw)
        errors = list(data.get("errors") or [])
        warnings = list(data.get("warnings") or [])
        passed = bool(data.get("passed", True)) and not any(
            e.get("severity") == "major" for e in errors
        )
        start_from = str(data.get("start_from") or "scenario_agent")
        if not passed and start_from not in ("research_agent", "scenario_agent"):
            start_from = "scenario_agent"
        return FactCheckResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            start_from=start_from,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(raw)
