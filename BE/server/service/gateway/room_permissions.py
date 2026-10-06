"""Room roles and the permission matrix (the only place that maps roles to rights).

Every room-level management action is authorized here, server-side, from the caller's
*stable user ID* and that user's membership in the room — never from a role or name sent
by the client.

  HOST         the signed-in user who created the room (canonical owner)
  CO_HOST      promoted by the host; helps run AI relay, recording and participants
  PARTICIPANT  everyone else; joins, talks, chats, but manages nothing room-wide

Targeted actions (mute, remove) only go *down* the hierarchy: a co-host acts on
participants, the host on co-hosts and participants, nobody on the host.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Optional

ROLE_HOST = "host"
ROLE_CO_HOST = "co_host"
ROLE_PARTICIPANT = "participant"
ROLES = (ROLE_HOST, ROLE_CO_HOST, ROLE_PARTICIPANT)

_RANK = {ROLE_HOST: 3, ROLE_CO_HOST: 2, ROLE_PARTICIPANT: 1}

PERMISSION_DENIED_MESSAGE = "You don't have permission to perform this action."


class Permission(str, Enum):
    MANAGE_AI = "can_manage_ai"
    MANAGE_RECORDING = "can_manage_recording"
    MUTE_PARTICIPANT = "can_mute_participant"
    REMOVE_PARTICIPANT = "can_remove_participant"
    MANAGE_ROOM_SECURITY = "can_manage_room_security"
    ASSIGN_COHOST = "can_assign_cohost"
    MANAGE_PASSWORD = "can_manage_password"
    LOCK_ROOM = "can_lock_room"
    EXTEND_ROOM = "can_extend_room"


_CO_HOST_PERMISSIONS: FrozenSet[Permission] = frozenset(
    {
        Permission.MANAGE_AI,
        Permission.MANAGE_RECORDING,
        Permission.MUTE_PARTICIPANT,
        Permission.REMOVE_PARTICIPANT,
    }
)

ROLE_PERMISSIONS: Dict[str, FrozenSet[Permission]] = {
    ROLE_HOST: frozenset(Permission),
    ROLE_CO_HOST: _CO_HOST_PERMISSIONS,
    ROLE_PARTICIPANT: frozenset(),
}

# Without sign-in (USER_AUTH_REQUIRED=false, local tests only) nobody has a stable
# identity, so roles cannot exist. Rooms then keep the legacy open behaviour for AI
# relay and recording; every identity-based action stays unavailable.
OPEN_MODE_PERMISSIONS: FrozenSet[Permission] = frozenset({Permission.MANAGE_AI, Permission.MANAGE_RECORDING})


class RoomPermissionError(Exception):
    """403: the authenticated caller's room role doesn't allow the action."""

    def __init__(self, message: str = PERMISSION_DENIED_MESSAGE, code: str = "permission_denied") -> None:
        super().__init__(message)
        self.code = code


def normalize_role(role: Optional[str]) -> str:
    return role if role in _RANK else ROLE_PARTICIPANT


def has_permission(role: Optional[str], permission: Permission, *, enforced: bool = True) -> bool:
    if not enforced:
        return permission in OPEN_MODE_PERMISSIONS
    return permission in ROLE_PERMISSIONS[normalize_role(role)]


def capabilities(role: Optional[str], *, enforced: bool = True) -> Dict[str, bool]:
    return {permission.value: has_permission(role, permission, enforced=enforced) for permission in Permission}


def outranks(actor_role: Optional[str], target_role: Optional[str]) -> bool:
    """True when the actor may act on the target (strictly higher role)."""
    return _RANK[normalize_role(actor_role)] > _RANK[normalize_role(target_role)]


def require(role: Optional[str], permission: Permission, *, enforced: bool = True) -> None:
    if not has_permission(role, permission, enforced=enforced):
        raise RoomPermissionError()
