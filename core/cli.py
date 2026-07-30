"""CLI for Phase 1 operations that have no UI yet.

Usage:
  uv run python -m core.cli set-key <installation_id> <anthropic_key>
  uv run python -m core.cli list-keys <installation_id>
"""

import asyncio
import sys

from sqlalchemy import select

from core.crypto import encrypt_key, fingerprint
from core.db.models import ApiKey
from core.db.session import get_session_factory


async def set_key(installation_id: int, plaintext: str) -> None:
    async with get_session_factory()() as session:
        session.add(
            ApiKey(
                installation_id=installation_id,
                provider="anthropic",
                ciphertext=encrypt_key(plaintext),
                key_fingerprint=fingerprint(plaintext),
            )
        )
        await session.commit()
    print(f"Stored key {fingerprint(plaintext)} for installation {installation_id}")


async def list_keys(installation_id: int) -> None:
    async with get_session_factory()() as session:
        rows = await session.scalars(
            select(ApiKey).where(ApiKey.installation_id == installation_id)
        )
        for r in rows:
            print(f"{r.provider}: {r.key_fingerprint} (created {r.created_at})")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, inst = sys.argv[1], int(sys.argv[2])
    if cmd == "set-key":
        asyncio.run(set_key(inst, sys.argv[3]))
    elif cmd == "list-keys":
        asyncio.run(list_keys(inst))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
