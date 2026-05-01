"""Compatibility package for legacy ``src.*`` imports.

Runtime source now lives under ``server/src`` in the backend package tree, while
older gateway, interpreter, and CLI modules still import ``src.*``. Keep this
package path as a small bridge so those imports continue to resolve in Docker
where ``/app`` is the Python import root.
"""
from pathlib import Path


_SERVER_SRC = Path(__file__).resolve().parents[1] / "server" / "src"
if _SERVER_SRC.is_dir():
    __path__.append(str(_SERVER_SRC))  # type: ignore[name-defined]
