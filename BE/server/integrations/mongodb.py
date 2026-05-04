import logging
from typing import Any, Optional

from server.config import Settings

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover - keeps non-Mongo installs bootable.
    AsyncIOMotorClient = None


logger = logging.getLogger(__name__)


def create_mongo_client(settings: Settings) -> Optional[Any]:
    if not settings.mongodb_url:
        logger.info("mongodb persistence disabled: MONGODB_URL is not set")
        return None

    if AsyncIOMotorClient is None:
        logger.warning("mongodb persistence disabled: motor package is not installed")
        return None

    return AsyncIOMotorClient(
        settings.mongodb_url,
        serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
        connectTimeoutMS=settings.mongodb_connect_timeout_ms,
        uuidRepresentation="standard",
    )


def get_mongo_database(client: Optional[Any], settings: Settings) -> Optional[Any]:
    if client is None:
        return None
    return client[settings.mongodb_database]


def close_mongo_client(client: Optional[Any]) -> None:
    if client is not None:
        client.close()
