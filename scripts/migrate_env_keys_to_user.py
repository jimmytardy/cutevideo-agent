#!/usr/bin/env python3
"""Migration ponctuelle vers des identifiants strictement par utilisateur (idempotente).

    python scripts/migrate_env_keys_to_user.py <email> [--env-file .env] [--dry-run]

1. Range les comptes de publication de l'ancien .env dans le compte `<email>` :
   YOUTUBE_REFRESH_TOKEN → clé `youtube`, INSTAGRAM_ACCESS_TOKEN (+ INSTAGRAM_PAGE_ID) → clé
   `instagram`. Une clé déjà enregistrée n'est jamais écrasée.
2. Rapport : clés de `<email>` testées (`validate_api_key`) et chaînes dont le propriétaire n'a
   pas de clé Anthropic (elles ne pourront plus créer de vidéo).

Les variables sont lues dans l'environnement, puis dans `--env-file`. Retirez-les ensuite du .env.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from sqlalchemy import select

from agent.core.api_key_validation import ApiKeyValidationError, validate_api_key
from agent.core.api_keys import decrypt_api_key, encrypt_api_key
from agent.core.database import AsyncSessionFactory, Channel, User, UserApiKey

PUBLISHING_VARS = ("YOUTUBE_REFRESH_TOKEN", "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_PAGE_ID")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.startswith("#"):
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _legacy_values(env_file: Path) -> dict[str, str]:
    from_file = _read_env_file(env_file)
    return {name: (os.getenv(name) or from_file.get(name) or "").strip() for name in PUBLISHING_VARS}


async def _add_key(session, user: User, provider: str, key: str, metadata: dict | None, dry_run: bool) -> str:
    existing = await session.scalar(
        select(UserApiKey).where(UserApiKey.user_id == user.id, UserApiKey.provider == provider)
    )
    if existing is not None:
        return "déjà présente (inchangée)"
    if not dry_run:
        session.add(UserApiKey(user_id=user.id, provider=provider, encrypted_key=encrypt_api_key(key), metadata_=metadata))
    return "ajoutée"


async def _report(session, user_id, email: str) -> None:
    rows = (await session.execute(select(UserApiKey).where(UserApiKey.user_id == user_id))).scalars().all()
    print(f"\nClés de {email} :")
    for row in sorted(rows, key=lambda r: r.provider):
        try:
            await validate_api_key(row.provider, decrypt_api_key(row.encrypted_key), row.metadata_)
            status = "valide (ou test non concluant)"
        except ApiKeyValidationError as exc:
            status = f"REFUSÉE : {exc}"
        print(f"  - {row.provider:<13} {status}")

    with_anthropic = set(
        (await session.execute(select(UserApiKey.user_id).where(UserApiKey.provider == "anthropic"))).scalars()
    )
    orphans = (
        await session.execute(
            select(Channel.name, User.email).join(User, User.id == Channel.user_id)
            .where(Channel.user_id.not_in(with_anthropic) if with_anthropic else True)
        )
    ).all()
    if orphans:
        print("\nChaînes sans clé Anthropic chez leur propriétaire (création de vidéo impossible) :")
        for name, email in orphans:
            print(f"  - {name} ({email})")


async def main(email: str, env_file: Path, dry_run: bool) -> None:
    legacy = _legacy_values(env_file)
    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            raise SystemExit(f"utilisateur inconnu : {email}")
        user_id = user.id

        if legacy["YOUTUBE_REFRESH_TOKEN"]:
            status = await _add_key(session, user, "youtube", legacy["YOUTUBE_REFRESH_TOKEN"], None, dry_run)
            print(f"YouTube (YOUTUBE_REFRESH_TOKEN) : {status}")
        if legacy["INSTAGRAM_ACCESS_TOKEN"]:
            meta = {"page_id": legacy["INSTAGRAM_PAGE_ID"]} if legacy["INSTAGRAM_PAGE_ID"] else None
            status = await _add_key(session, user, "instagram", legacy["INSTAGRAM_ACCESS_TOKEN"], meta, dry_run)
            print(f"Instagram (INSTAGRAM_ACCESS_TOKEN) : {status}")
        if dry_run:
            await session.rollback()
            print("(dry-run : rien n'est écrit)")
        else:
            await session.commit()
        await _report(session, user_id, email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", help="compte qui reçoit les identifiants de publication du .env")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.env_file, args.dry_run))
