from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from server.config import Settings
from server.service.brain_runtime.daemon import InterpreterDaemon
from server.redis import close_redis, create_redis_client, ping_redis


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_PROJECT_ROOT / ".env")


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run() -> int:
    settings = Settings()
    redis = await create_redis_client(settings.redis_url)
    daemon = InterpreterDaemon(settings, redis)

    try:
        await ping_redis(redis)
        await daemon.run()
        return 0
    finally:
        await close_redis(redis)


def main() -> int:
    _configure_logging()
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
