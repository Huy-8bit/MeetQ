import logging
from typing import Any, Optional
from urllib.parse import quote_plus, urlsplit, urlunsplit

from server.config import Settings

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # pragma: no cover - keeps non-Mongo installs bootable.
    AsyncIOMotorClient = None


logger = logging.getLogger(__name__)


def create_mongo_client(settings: Settings) -> Optional[Any]:
    mongodb_url = _effective_mongodb_url(settings)
    if not mongodb_url:
        return None

    if AsyncIOMotorClient is None:
        logger.warning("mongodb persistence disabled: motor package is not installed")
        return None

    return AsyncIOMotorClient(
        mongodb_url,
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


def _effective_mongodb_url(settings: Settings) -> Optional[str]:
    explicit_url = (settings.mongodb_url or "").strip()
    if explicit_url:
        if _mongodb_url_has_credentials(explicit_url):
            logger.info(
                "mongodb persistence enabled with credentialed MONGODB_URL database=%s",
                settings.mongodb_database,
            )
            return explicit_url
        if settings.mongodb_username and settings.mongodb_password:
            logger.warning(
                "MONGODB_URL does not include credentials; injecting MONGODB_USERNAME/"
                "MONGODB_PASSWORD into the configured MongoDB URL"
            )
            return _build_credentialed_mongodb_url(settings, explicit_url)
        logger.warning(
            "mongodb persistence disabled: MONGODB_URL has no credentials and "
            "MONGODB_USERNAME/MONGODB_PASSWORD are not both set"
        )
        return None

    if settings.mongodb_username and settings.mongodb_password:
        return _build_field_based_mongodb_url(settings)

    if settings.mongodb_username or settings.mongodb_password:
        logger.warning(
            "mongodb persistence disabled: incomplete MongoDB credentials; set both "
            "MONGODB_USERNAME and MONGODB_PASSWORD"
        )
        return None

    logger.info(
        "mongodb persistence disabled: set credentialed MONGODB_URL or "
        "MONGODB_USERNAME/MONGODB_PASSWORD"
    )
    return None


def _build_field_based_mongodb_url(settings: Settings) -> str:
    host = settings.mongodb_host
    port = settings.mongodb_port
    url = f"mongodb://{host}:{port}/{quote_plus(settings.mongodb_database)}"
    logger.info(
        "mongodb persistence enabled with field-based credentials host=%s port=%s "
        "database=%s auth_source=%s",
        host,
        port,
        settings.mongodb_database,
        settings.mongodb_auth_source or settings.mongodb_database,
    )
    return _build_credentialed_mongodb_url(settings, url)


def _build_credentialed_mongodb_url(settings: Settings, url: str) -> str:
    parsed = urlsplit(url)
    username = quote_plus(settings.mongodb_username or "")
    password = quote_plus(settings.mongodb_password or "")
    auth_source = quote_plus(settings.mongodb_auth_source or settings.mongodb_database)
    path = parsed.path if parsed.path and parsed.path != "/" else f"/{quote_plus(settings.mongodb_database)}"
    query = parsed.query
    if "authSource=" not in query:
        query = f"{query}&authSource={auth_source}" if query else f"authSource={auth_source}"
    netloc = f"{username}:{password}@{parsed.netloc}"
    return urlunsplit((parsed.scheme, netloc, path, query, parsed.fragment))


def _mongodb_url_has_credentials(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return bool(parsed.username and parsed.password)
