"""MongoDB access: driver checks (pymongo) and the native dump/restore tools.

Passwords never appear on a command line: mongodump/mongorestore get the URI
without password plus `--config <file>` (mode 0600) that holds the password.
With --use-docker the same commands run in the official `mongo:<major>` image.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from tools.db_backup.config import DatabaseTarget, mask_secrets

CONNECT_TIMEOUT_MS = 8000
SUPPORTED_SERVER_MAJORS = range(4, 9)  # MongoDB Database Tools 100.x: server 4.x–8.x
DOCKER_HOST_ALIASES = {"localhost", "127.0.0.1", "::1"}


class DatabaseError(Exception):
    pass


class ToolError(Exception):
    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


@dataclass
class DatabaseInfo:
    server_version: str
    database: str
    is_replica_set: bool
    collections: List[Dict[str, Any]]
    data_size: int
    storage_size: int
    index_size: int

    @property
    def major(self) -> int:
        return int(self.server_version.split(".")[0])

    @property
    def user_collections(self) -> List[Dict[str, Any]]:
        return [c for c in self.collections if not c["name"].startswith("system.")]


def _client(target: DatabaseTarget) -> Any:
    from pymongo import MongoClient

    return MongoClient(
        target.full_uri,
        serverSelectionTimeoutMS=CONNECT_TIMEOUT_MS,
        connectTimeoutMS=CONNECT_TIMEOUT_MS,
        socketTimeoutMS=60_000,
        appname="meetq-db-backup",
    )


def inspect_database(target: DatabaseTarget, *, with_counts: bool = True) -> DatabaseInfo:
    """Connectivity + metadata. Raises DatabaseError with a sanitized message."""
    try:
        client = _client(target)
        try:
            client.admin.command("ping")
            build = client.admin.command("buildInfo")
            try:
                hello = client.admin.command("hello")
            except Exception:
                hello = {}
            db = client[target.database]
            try:
                stats = db.command("dbStats")
            except Exception:
                stats = {}
            collections = []
            for spec in db.list_collections():
                name = spec["name"]
                kind = spec.get("type", "collection")
                entry: Dict[str, Any] = {"name": name, "type": kind}
                # system.* (e.g. system.views) hold metadata and are not countable.
                if kind == "collection" and with_counts and not name.startswith("system."):
                    entry["documents"] = db[name].estimated_document_count()
                    entry["indexes"] = sorted(index["name"] for index in db[name].list_indexes())
                collections.append(entry)
            collections.sort(key=lambda c: c["name"])
        finally:
            client.close()
    except Exception as exc:
        raise DatabaseError(f"Cannot use database {target.safe_url}: {mask_secrets(str(exc), [target.password])}") from exc
    return DatabaseInfo(
        server_version=str(build.get("version", "0")),
        database=target.database,
        is_replica_set=bool(hello.get("setName")),
        collections=collections,
        data_size=int(stats.get("dataSize", 0) or 0),
        storage_size=int(stats.get("storageSize", 0) or 0),
        index_size=int(stats.get("indexSize", 0) or 0),
    )


def active_connections(target: DatabaseTarget) -> Optional[int]:
    """Client connections to the server, if the user may see them (best effort)."""
    try:
        client = _client(target)
        try:
            status = client.admin.command("serverStatus")
        finally:
            client.close()
        return int(status["connections"]["current"]) - 1
    except Exception:
        return None


# ── Native tools ────────────────────────────────────────────────────────────


@dataclass
class ToolRunner:
    """Runs mongodump/mongorestore locally or in Docker, with the password in a 0600 file."""

    use_docker: bool = False
    docker_network: str = "host"
    docker_image: Optional[str] = None
    _child: Optional[subprocess.Popen] = None

    def version(self, tool: str = "mongodump", server_major: Optional[int] = None) -> str:
        output = self._run([tool, "--version"], workdir=None, target=None, server_major=server_major).strip()
        match = re.search(r"version:?\s*r?(\d+\.\d+\.\d+)", output)
        return match.group(1) if match else output.splitlines()[0] if output else "unknown"

    def available(self, tool: str = "mongodump") -> bool:
        if self.use_docker:
            return shutil.which("docker") is not None
        return shutil.which(tool) is not None

    def image(self, server_major: Optional[int]) -> str:
        if self.docker_image:
            return self.docker_image
        return f"mongo:{server_major or 7}"

    def run(
        self,
        tool: str,
        args: Sequence[str],
        *,
        target: DatabaseTarget,
        workdir: Path,
        server_major: Optional[int],
    ) -> str:
        return self._run([tool, *args], workdir=workdir, target=target, server_major=server_major)

    def _docker_target(self, target: DatabaseTarget) -> DatabaseTarget:
        if self.docker_network == "host":
            return target
        hosts = []
        for host in target.hosts.split(","):
            name, _, port = host.rpartition(":") if ":" in host else (host, "", "")
            name = name or host
            if name in DOCKER_HOST_ALIASES:
                name = "host.docker.internal"
            hosts.append(f"{name}:{port}" if port else name)
        return target.with_hosts(",".join(hosts))

    def _run(self, command: List[str], *, workdir: Optional[Path], target: Optional[DatabaseTarget], server_major: Optional[int]) -> str:
        config_path: Optional[Path] = None
        secrets = [target.password if target else None]
        try:
            if target is not None:
                effective = self._docker_target(target) if self.use_docker else target
                command = [command[0], f"--uri={effective.uri_without_password}", *command[1:]]
                if target.password is not None:
                    assert workdir is not None
                    config_path = workdir / ".mongo-tools.yaml"
                    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as handle:
                        # YAML double-quoted string; escape backslashes and quotes.
                        escaped = target.password.replace("\\", "\\\\").replace('"', '\\"')
                        handle.write(f'password: "{escaped}"\n')
                    command.append(f"--config={'/work/.mongo-tools.yaml' if self.use_docker else config_path}")
            if self.use_docker:
                docker = ["docker", "run", "--rm", "--network", self.docker_network, "--add-host=host.docker.internal:host-gateway"]
                if workdir is not None:
                    docker += ["-v", f"{workdir}:/work", "-w", "/work"]
                command = [*docker, self.image(server_major), *command]
            return self._exec(command, secrets)
        finally:
            if config_path is not None:
                config_path.unlink(missing_ok=True)

    def _exec(self, command: List[str], secrets: List[Optional[str]]) -> str:
        try:
            self._child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError as exc:
            raise ToolError(f"{command[0]} is not installed.") from exc
        try:
            output, _ = self._child.communicate()
        except BaseException:
            self.terminate()
            raise
        code = self._child.returncode
        self._child = None
        output = mask_secrets(output or "", secrets)
        if code != 0:
            raise ToolError(f"{Path(command[0]).name if command[0] != 'docker' else 'docker ' + command[-1]} exited with {code}", output)
        return output

    def terminate(self) -> None:
        child = self._child
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        self._child = None


def tail(output: str, lines: int = 12) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])


def make_work_dir(base: Path, operation: str) -> Path:
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return Path(tempfile.mkdtemp(prefix=f"meetq-db-backup-{operation}-", dir=base))
