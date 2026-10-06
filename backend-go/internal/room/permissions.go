package room

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"

	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/store"
)

// Permission names (server/service/gateway/room_permissions.py).
const (
	PermManageAI           = "can_manage_ai"
	PermManageRecording    = "can_manage_recording"
	PermMuteParticipant    = "can_mute_participant"
	PermRemoveParticipant  = "can_remove_participant"
	PermManageRoomSecurity = "can_manage_room_security"
	PermAssignCoHost       = "can_assign_cohost"
	PermManagePassword     = "can_manage_password"
	PermLockRoom           = "can_lock_room"
	PermExtendRoom         = "can_extend_room"
)

// AllPermissions keeps the Python enum order (response dict order).
var AllPermissions = []string{
	PermManageAI, PermManageRecording, PermMuteParticipant, PermRemoveParticipant,
	PermManageRoomSecurity, PermAssignCoHost, PermManagePassword, PermLockRoom, PermExtendRoom,
}

var coHostPermissions = map[string]bool{
	PermManageAI: true, PermManageRecording: true, PermMuteParticipant: true, PermRemoveParticipant: true,
}

var openModePermissions = map[string]bool{PermManageAI: true, PermManageRecording: true}

const PermissionDeniedMessage = "You don't have permission to perform this action."

var rank = map[string]int{models.RoleHost: 3, models.RoleCoHost: 2, models.RoleParticipant: 1}

// PermissionError is the 403 for a role that doesn't allow the action.
type PermissionError struct {
	Code    string
	Message string
}

func (e *PermissionError) Error() string { return e.Message }

func ErrPermissionDenied() *PermissionError {
	return &PermissionError{Code: "permission_denied", Message: PermissionDeniedMessage}
}

func NormalizeRole(role string) string {
	if _, ok := rank[role]; ok {
		return role
	}
	return models.RoleParticipant
}

func HasPermission(role, permission string, enforced bool) bool {
	if !enforced {
		return openModePermissions[permission]
	}
	switch NormalizeRole(role) {
	case models.RoleHost:
		return true
	case models.RoleCoHost:
		return coHostPermissions[permission]
	}
	return false
}

// OrderedPermissions is capabilities() as an ordered JSON object.
type OrderedPermissions []struct {
	Name  string
	Value bool
}

func (p OrderedPermissions) MarshalJSON() ([]byte, error) {
	buf := []byte{'{'}
	for i, item := range p {
		if i > 0 {
			buf = append(buf, ',')
		}
		key, _ := json.Marshal(item.Name)
		buf = append(buf, key...)
		buf = append(buf, ':')
		if item.Value {
			buf = append(buf, "true"...)
		} else {
			buf = append(buf, "false"...)
		}
	}
	return append(buf, '}'), nil
}

func Capabilities(role string, enforced bool) OrderedPermissions {
	out := make(OrderedPermissions, 0, len(AllPermissions))
	for _, name := range AllPermissions {
		out = append(out, struct {
			Name  string
			Value bool
		}{name, HasPermission(role, name, enforced)})
	}
	return out
}

func Outranks(actor, target string) bool {
	return rank[NormalizeRole(actor)] > rank[NormalizeRole(target)]
}

// ── Live membership (room_membership.py) ──────────────────────────────────

type Member struct {
	UserID          string  `json:"-"`
	Role            string  `json:"role"`
	JoinedAt        *string `json:"joined_at"`
	CreatedAt       *string `json:"created_at,omitempty"`
	RemovedAt       *string `json:"removed_at,omitempty"`
	RemovedByUserID *string `json:"removed_by_user_id,omitempty"`
}

type MembershipStore struct {
	R   *redis.Client
	TTL time.Duration
}

func (m *MembershipStore) touch(ctx context.Context, roomID string) {
	_ = m.R.Expire(ctx, store.MembersKey(roomID), m.TTL).Err()
	_ = m.R.Expire(ctx, store.ParticipantUsersKey(roomID), m.TTL).Err()
}

// Get returns the member as a raw map (to keep unknown fields) plus the typed view.
func (m *MembershipStore) Get(ctx context.Context, roomID, userID string) (map[string]any, error) {
	if userID == "" {
		return nil, nil
	}
	raw, err := m.R.HGet(ctx, store.MembersKey(roomID), userID).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var member map[string]any
	if json.Unmarshal(raw, &member) != nil {
		return nil, nil
	}
	member["role"] = NormalizeRole(str(member["role"]))
	return member, nil
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func (m *MembershipStore) Put(ctx context.Context, roomID, userID string, member map[string]any) error {
	stored := map[string]any{}
	for k, v := range member {
		if k != "user_id" {
			stored[k] = v
		}
	}
	stored["role"] = NormalizeRole(str(stored["role"]))
	raw, _ := json.Marshal(stored)
	if err := m.R.HSet(ctx, store.MembersKey(roomID), userID, raw).Err(); err != nil {
		return err
	}
	m.touch(ctx, roomID)
	return nil
}

func (m *MembershipStore) SetHost(ctx context.Context, roomID, userID, createdAt string) error {
	return m.Put(ctx, roomID, userID, map[string]any{"role": models.RoleHost, "created_at": createdAt, "joined_at": nil})
}

// EnsureMember keeps an existing role or creates a PARTICIPANT; records the first join.
func (m *MembershipStore) EnsureMember(ctx context.Context, roomID, userID, joinedAt string) (map[string]any, error) {
	member, err := m.Get(ctx, roomID, userID)
	if err != nil {
		return nil, err
	}
	if member == nil {
		member = map[string]any{"role": models.RoleParticipant, "joined_at": joinedAt}
		return member, m.Put(ctx, roomID, userID, member)
	}
	if str(member["joined_at"]) == "" {
		member["joined_at"] = joinedAt
		return member, m.Put(ctx, roomID, userID, member)
	}
	return member, nil
}

func (m *MembershipStore) Update(ctx context.Context, roomID, userID string, patch map[string]any) error {
	member, err := m.Get(ctx, roomID, userID)
	if err != nil || member == nil {
		return err
	}
	for k, v := range patch {
		member[k] = v
	}
	return m.Put(ctx, roomID, userID, member)
}

func (m *MembershipStore) LinkParticipant(ctx context.Context, roomID, participantID, userID string) error {
	if err := m.R.HSet(ctx, store.ParticipantUsersKey(roomID), participantID, userID).Err(); err != nil {
		return err
	}
	m.touch(ctx, roomID)
	return nil
}

func (m *MembershipStore) UserForParticipant(ctx context.Context, roomID, participantID string) (string, error) {
	if participantID == "" {
		return "", nil
	}
	userID, err := m.R.HGet(ctx, store.ParticipantUsersKey(roomID), participantID).Result()
	if errors.Is(err, redis.Nil) {
		return "", nil
	}
	return userID, err
}

func (m *MembershipStore) ParticipantsForUser(ctx context.Context, roomID, userID string) ([]string, error) {
	mapping, err := m.R.HGetAll(ctx, store.ParticipantUsersKey(roomID)).Result()
	if err != nil {
		return nil, err
	}
	var out []string
	for participantID, owner := range mapping {
		if owner == userID {
			out = append(out, participantID)
		}
	}
	return out, nil
}
