"""Configuration from environment variables (and an optional .env.backup file).

Secrets (database password, AWS keys) are read from the environment only and are
never printed: `DatabaseTarget.safe_url` is what logs and reports show.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional
from urllib.parse import quote, unquote, urlencode, urlsplit, parse_qsl

BACKUP_ENVIRONMENTS = ("dev", "staging", "prod")
ENVIRONMENT_ALIASES = {"production": "prod", "development": "dev", "stage": "staging"}
# Restore targets also include places that are never backup sources.
TARGET_ENVIRONMENTS = BACKUP_ENVIRONMENTS + ("local", "test", "custom")

DEFAULT_TMP_DIR = "/tmp/meetq-db-backup"
DEFAULT_PREFIX = "database-backups"


class ConfigError(Exception):
    """Invalid or missing configuration (exit code 2)."""


def normalize_environment(value: Optional[str], *, allowed=BACKUP_ENVIRONMENTS, what: str = "environment") -> str:
    raw = (value or "").strip().lower()
    env = ENVIRONMENT_ALIASES.get(raw, raw)
    if env not in allowed:
        raise ConfigError(f"Invalid {what} {value!r}. Use one of: {', '.join(allowed)}.")
    return env


def is_production(env: str) -> bool:
    return env == "prod"


def load_env_file(path: Path, environ: Dict[str, str]) -> None:
    """KEY=VALUE lines; values already in the environment win (explicit beats file)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in environ:
            environ[key] = value


@dataclass(frozen=True)
class DatabaseTarget:
    """A MongoDB database. The password is kept apart from the URI."""

    hosts: str  # "host:port[,host:port]"
    database: str
    username: Optional[str] = None
    password: Optional[str] = field(default=None, repr=False)
    options: Mapping[str, str] = field(default_factory=dict)
    scheme: str = "mongodb"

    @property
    def uri_without_password(self) -> str:
        """Safe to put on a command line: credentials except the password."""
        user = f"{quote(self.username, safe='')}@" if self.username else ""
        query = f"?{urlencode(dict(self.options))}" if self.options else ""
        return f"{self.scheme}://{user}{self.hosts}/{self.database}{query}"

    @property
    def safe_url(self) -> str:
        user = f"{quote(self.username, safe='')}:***@" if self.username else ""
        query = f"?{urlencode(dict(self.options))}" if self.options else ""
        return f"{self.scheme}://{user}{self.hosts}/{self.database}{query}"

    @property
    def full_uri(self) -> str:
        """For the in-process driver only; never logged or passed to a subprocess."""
        creds = ""
        if self.username:
            creds = quote(self.username, safe="")
            if self.password is not None:
                creds += ":" + quote(self.password, safe="")
            creds += "@"
        query = f"?{urlencode(dict(self.options))}" if self.options else ""
        return f"{self.scheme}://{creds}{self.hosts}/{self.database}{query}"

    @property
    def identity(self) -> str:
        """Host list + database, for "is this the same database?" checks."""
        return f"{','.join(sorted(h.lower() for h in self.hosts.split(',')))}/{self.database}"

    def with_hosts(self, hosts: str) -> "DatabaseTarget":
        return DatabaseTarget(hosts, self.database, self.username, self.password, dict(self.options), self.scheme)

    def with_database(self, database: str) -> "DatabaseTarget":
        return DatabaseTarget(self.hosts, database, self.username, self.password, dict(self.options), self.scheme)


def parse_database_url(url: str, *, default_database: Optional[str] = None) -> DatabaseTarget:
    url = (url or "").strip()
    match = re.match(r"^(mongodb(?:\+srv)?)://(?:([^@/]*)@)?([^/?]+)(?:/([^?]*))?(?:\?(.*))?$", url)
    if not match:
        raise ConfigError("Database URL must look like mongodb://user:password@host:27017/database")
    scheme, creds, hosts, database, query = match.groups()
    username = password = None
    if creds:
        if ":" in creds:
            user, pw = creds.split(":", 1)
            username, password = unquote(user), unquote(pw)
        else:
            username = unquote(creds)
    database = unquote(database or "") or default_database
    if not database:
        raise ConfigError("Database URL must include the database name (…/<database>).")
    options = dict(parse_qsl(query or "", keep_blank_values=True))
    return DatabaseTarget(hosts=hosts, database=database, username=username, password=password, options=options, scheme=scheme)


def database_from_env(env: Mapping[str, str]) -> Optional[DatabaseTarget]:
    """DATABASE_URL, else the application's MONGODB_* settings."""
    explicit_password = env.get("DB_PASSWORD") or env.get("MONGODB_PASSWORD")
    for key in ("DATABASE_URL", "MONGODB_URL"):
        if env.get(key):
            target = parse_database_url(env[key], default_database=env.get("DB_NAME") or env.get("MONGODB_DATABASE"))
            if target.username and target.password is None and explicit_password:
                target = DatabaseTarget(target.hosts, target.database, target.username, explicit_password, dict(target.options), target.scheme)
            return target
    host = env.get("DB_HOST") or env.get("MONGODB_HOST")
    if not host:
        return None
    port = env.get("DB_PORT") or env.get("MONGODB_PORT") or "27017"
    database = env.get("DB_NAME") or env.get("MONGODB_DATABASE")
    if not database:
        raise ConfigError("Set DB_NAME (or MONGODB_DATABASE) with DB_HOST.")
    username = env.get("DB_USER") or env.get("MONGODB_USERNAME") or None
    options: Dict[str, str] = {}
    auth_source = env.get("DB_AUTH_SOURCE") or env.get("MONGODB_AUTH_SOURCE")
    if auth_source and username:
        options["authSource"] = auth_source
    return DatabaseTarget(hosts=f"{host}:{port}", database=database, username=username, password=explicit_password, options=options)


@dataclass
class Settings:
    environment: str
    bucket: Optional[str]
    prefix: str
    aws_region: Optional[str]
    s3_endpoint_url: Optional[str]
    tmp_dir: Path
    keep_local: bool
    retention_days: int
    min_backups_to_keep: int
    restore_jobs: int
    database: Optional[DatabaseTarget]
    use_docker: bool
    docker_network: str
    docker_image: Optional[str]
    notify_telegram: bool
    telegram_bot_token: Optional[str] = field(default=None, repr=False)
    telegram_chat_id: Optional[str] = None
    git_commit: Optional[str] = None

    def require_bucket(self) -> str:
        if not self.bucket:
            raise ConfigError("DB_BACKUP_S3_BUCKET is not set.")
        return self.bucket

    def require_database(self) -> DatabaseTarget:
        if self.database is None:
            raise ConfigError("Set DATABASE_URL (or MONGODB_URL / DB_HOST + DB_NAME) for the database to back up.")
        return self.database


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(env: Mapping[str, str], key: str, default: int, *, minimum: int = 0, maximum: int = 10_000) -> int:
    raw = env.get(key)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number.")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}.")
    return value


def build_settings(env: Mapping[str, str], *, environment: Optional[str] = None) -> Settings:
    """`environment` (from --environment) must agree with BACKUP_ENVIRONMENT when both are set."""
    configured = env.get("BACKUP_ENVIRONMENT")
    if environment and configured and normalize_environment(environment) != normalize_environment(configured):
        raise ConfigError(
            f"--environment {environment} does not match BACKUP_ENVIRONMENT={configured}. "
            "Use the env file of the environment you mean to back up."
        )
    chosen = environment or configured
    if not chosen:
        raise ConfigError("Set BACKUP_ENVIRONMENT (dev, staging or prod) or pass --environment.")
    prefix = (env.get("DB_BACKUP_S3_PREFIX") or DEFAULT_PREFIX).strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", prefix):
        raise ConfigError("DB_BACKUP_S3_PREFIX may only contain letters, digits, '.', '_', '-', '/'.")
    return Settings(
        environment=normalize_environment(chosen),
        bucket=(env.get("DB_BACKUP_S3_BUCKET") or "").strip() or None,
        prefix=prefix,
        aws_region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or None,
        s3_endpoint_url=env.get("DB_BACKUP_S3_ENDPOINT_URL") or None,
        tmp_dir=Path(env.get("BACKUP_TMP_DIR") or DEFAULT_TMP_DIR),
        keep_local=_bool(env.get("KEEP_LOCAL_BACKUP")),
        retention_days=_int(env, "BACKUP_RETENTION_DAYS", 30, minimum=1, maximum=3650),
        min_backups_to_keep=_int(env, "MIN_BACKUPS_TO_KEEP", 3, minimum=1, maximum=1000),
        restore_jobs=_int(env, "RESTORE_JOBS", 4, minimum=1, maximum=16),
        database=database_from_env(env),
        use_docker=_bool(env.get("BACKUP_USE_DOCKER")),
        docker_network=env.get("BACKUP_DOCKER_NETWORK") or "host",
        docker_image=env.get("BACKUP_DOCKER_IMAGE") or None,
        notify_telegram=_bool(env.get("BACKUP_NOTIFY_TELEGRAM")),
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
        git_commit=env.get("GIT_COMMIT") or None,
    )


def mask_secrets(text: str, secrets: List[Optional[str]]) -> str:
    """Last line of defence for tool output that might echo a secret."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return re.sub(r"(mongodb(?:\+srv)?://[^:/@\s]+):[^@\s]+@", r"\1:***@", text)
