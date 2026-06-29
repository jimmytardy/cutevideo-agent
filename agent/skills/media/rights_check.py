from __future__ import annotations

import logging
import re
from typing import Any

from agent.core.config import load_agent_config
from agent.core.database import MediaAsset

logger = logging.getLogger(__name__)

_PUBLISHABLE_LICENSES: frozenset[str] = frozenset({
    "CC0",
    "PD",
    "CC-BY",
    "pexels",
    "unsplash",
    "pixabay",
    "coverr",
    "ai_generated",
})

_ATTRIBUTION_REQUIRED: frozenset[str] = frozenset({"CC-BY"})

_REJECTED_LICENSE_PATTERNS: tuple[str, ...] = (
    "CC-BY-SA",
    "CC BY-SA",
    "CC-BY-NC",
    "CC BY-NC",
    "CC-BY-ND",
    "CC BY-ND",
    "proprietary",
)

_AI_SOURCE_ALIASES: frozenset[str] = frozenset({"ai_image", "ai"})


def _load_publishable_licenses() -> frozenset[str]:
    cfg = load_agent_config().get("media_sources", {})
    raw = cfg.get("publishable_licenses")
    if isinstance(raw, list) and raw:
        return frozenset(str(x) for x in raw)
    return _PUBLISHABLE_LICENSES


def normalize_license(raw: str | None, *, source: str | None = None) -> str | None:
    if not raw or not str(raw).strip():
        if source in _AI_SOURCE_ALIASES:
            return "ai_generated"
        return None

    text = str(raw).strip()
    lower = text.lower()

    if source in _AI_SOURCE_ALIASES or "synthetic-ai-generated" in lower or lower == "ai_generated":
        return "ai_generated"

    if any(p.lower() in lower for p in _REJECTED_LICENSE_PATTERNS):
        if "cc-by-sa" in lower.replace(" ", "-") or "cc by-sa" in lower:
            return "CC-BY-SA"
        if "nc" in lower and ("cc-by" in lower.replace(" ", "-") or "cc by" in lower):
            return "CC-BY-NC"
        if "nd" in lower and ("cc-by" in lower.replace(" ", "-") or "cc by" in lower):
            return "CC-BY-ND"
        if "proprietary" in lower or "runway" in lower:
            return "proprietary"

    if "creativecommons.org/publicdomain/zero" in lower or lower in {"cc0", "cc-0", "cc0 1.0"}:
        return "CC0"
    if "cc0" in lower and "nc" not in lower and "sa" not in lower:
        return "CC0"

    if "public domain" in lower or lower in {"pd", "pdm"} or "domaine public" in lower:
        return "PD"
    if "nasa" in lower and "domaine" in lower:
        return "PD"

    if "creativecommons.org/licenses/by/" in lower and "nc" not in lower and "nd" not in lower and "sa" not in lower:
        return "CC-BY"
    if re.search(r"cc[\s-]?by(?![\s-]?(sa|nc|nd))", lower):
        return "CC-BY"

    if "pexels" in lower:
        return "pexels"
    if "unsplash" in lower:
        return "unsplash"
    if "pixabay" in lower:
        return "pixabay"
    if "coverr" in lower:
        return "coverr"

    if "cc-by-sa" in lower.replace(" ", "-") or "cc by-sa" in lower:
        return "CC-BY-SA"

    return text


def requires_attribution_for(license_norm: str) -> bool:
    return license_norm in _ATTRIBUTION_REQUIRED


def _item_license(item: dict[str, Any] | MediaAsset) -> str | None:
    if isinstance(item, MediaAsset):
        return normalize_license(item.license, source=item.source)
    license_raw = item.get("license")
    source = item.get("source")
    return normalize_license(license_raw, source=source)


def is_publishable(item: dict[str, Any] | MediaAsset) -> tuple[bool, str]:
    license_norm = _item_license(item)
    if not license_norm:
        return False, "license_unknown"

    publishable = _load_publishable_licenses()
    if license_norm not in publishable:
        return False, f"license_not_publishable:{license_norm}"

    return True, "ok"


def _extract_author(item: dict[str, Any]) -> str | None:
    for key in ("author", "creator", "artist", "photographer", "name"):
        val = item.get(key)
        if val and str(val).strip():
            return str(val).strip()

    attribution = str(item.get("attribution") or "").strip()
    source = str(item.get("source") or "").lower()
    if not attribution:
        return None

    if source == "wikimedia":
        if " — " in attribution:
            return attribution.split(" — ", 1)[-1].strip() or None
    if source == "gallica":
        if attribution.startswith("Gallica BnF — "):
            return attribution[len("Gallica BnF — "):].strip() or None
    if source == "pexels":
        m = re.match(r"(?:Photo|Vidéo) par (.+?) via Pexels", attribution)
        if m:
            return m.group(1).strip()
    if source == "unsplash":
        m = re.match(r"Photo par (.+?) sur Unsplash", attribution)
        if m:
            return m.group(1).strip()
    if source == "pixabay":
        m = re.match(r"(?:Image|Vidéo) par (.+?) sur Pixabay", attribution)
        if m:
            return m.group(1).strip()
    if source == "europeana":
        if " via Europeana" in attribution:
            part = attribution.split(" via Europeana", 1)[0].strip()
            if " — " in part:
                return part.split(" — ", 1)[-1].strip() or part
            return part or None
    if source == "nasa":
        if attribution.startswith("NASA / "):
            rest = attribution[len("NASA / "):]
            if " — " in rest:
                return rest.split(" — ", 1)[0].strip()
            return rest.strip() or "NASA"

    return None


def enrich_candidate(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    source = str(enriched.get("source") or "").lower()

    if not enriched.get("source_url"):
        url = enriched.get("url") or enriched.get("local_generated")
        if url:
            enriched["source_url"] = str(url)

    license_norm = normalize_license(enriched.get("license"), source=source or None)
    if source in _AI_SOURCE_ALIASES and not license_norm:
        license_norm = "ai_generated"
    enriched["license"] = license_norm

    author = _extract_author(enriched)
    if author:
        enriched["author"] = author

    if license_norm:
        enriched["requires_attribution"] = requires_attribution_for(license_norm)
    else:
        enriched["requires_attribution"] = False

    return enriched


def filter_publishable(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in candidates:
        item = enrich_candidate(raw)
        ok, reason = is_publishable(item)
        if ok:
            accepted.append(item)
        else:
            item["_rejection_category"] = "license_rejected"
            item["_relevance_reason"] = reason
            rejected.append(item)
            logger.debug(
                "Asset refusé (licence) source=%s license=%s reason=%s",
                item.get("source"),
                item.get("license"),
                reason,
            )
    return accepted, rejected


def media_asset_rights_fields(item: dict[str, Any]) -> dict[str, Any]:
    enriched = enrich_candidate(item)
    return {
        "source_url": enriched.get("source_url") or enriched.get("url"),
        "license": enriched.get("license"),
        "attribution": enriched.get("attribution"),
        "author": enriched.get("author"),
        "requires_attribution": bool(enriched.get("requires_attribution")),
    }


def build_credits_block(assets: list[MediaAsset]) -> str:
    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []

    for asset in assets:
        if not asset.requires_attribution:
            continue
        author = (asset.author or asset.attribution or "Auteur inconnu").strip()
        license_label = (asset.license or "licence inconnue").strip()
        source_url = (asset.source_url or "").strip()
        key = (author, license_label, source_url)
        if key in seen:
            continue
        seen.add(key)
        asset_label = "Vidéo" if asset.asset_type == "video" else "Image"
        if source_url:
            lines.append(f"{asset_label} : {author} — {license_label} — {source_url}")
        else:
            lines.append(f"{asset_label} : {author} — {license_label}")

    if not lines:
        return ""
    return "Crédits :\n" + "\n".join(lines)
