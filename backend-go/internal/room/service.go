package room

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"

	"meetq/backend-go/internal/ai"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/httpx"
	"meetq/backend-go/internal/livekit"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/notify"
	"meetq/backend-go/internal/platform"
	"meetq/backend-go/internal/store"
)

// Domain errors (mapped to HTTP per endpoint, as in api_rooms.py).
var (
	ErrRoomNotFound        = errors.New("room not found")
	ErrRoomExpired         = errors.New("room expired")
	ErrRoomFull            = errors.New("room full")
	ErrRoomLocked          = errors.New("room locked")
	ErrParticipantRemoved  = errors.New("participant removed")
	ErrParticipantNotFound = errors.New("participant not found")
)

type InvalidLanguageError struct {
	Message string
	Details map[string]any
}

func (e *InvalidLanguageError) Error() string { return e.Message }

type InvalidMeetingLanguagesError struct {
	Message string
	Details map[string]any
}

func (e *InvalidMeetingLanguagesError) Error() string { return e.Message }

// BrseForbiddenError is BrseToggleForbiddenError (403, or 409 for session_mismatch).
type BrseForbiddenError struct {
	Code    string
	Message string
}

func (e *BrseForbiddenError) Error() string { return e.Message }

type RelayModeNotSupportedError struct{ Message string }

func (e *RelayModeNotSupportedError) Error() string { return e.Message }

// ActionError is RoomActionError: a management request that can't be carried out.
type ActionError struct {
	Status  int
	Code    string
	Message string
}

func (e *ActionError) Error() string { return e.Message }

type ChatError struct {
	Code    string
	Message string
}

func (e *ChatError) Error() string { return e.Message }

// RecordingHooks is what the room domain needs from recording (archive package).
type RecordingHooks interface {
	Available() bool
	Current(ctx context.Context, roomID string) (map[string]any, error)
	StopForRoomEnd(ctx context.Context, roomID, reason string)
}

type Service struct {
	Cfg       *config.Config
	Store     *store.RoomStore
	Access    *AccessStore
	Members   *MembershipStore
	History   *history.Repository
	LiveKit   *livekit.Client
	AI        *ai.Client
	Notifier  *notify.Telegram
	Recording RecordingHooks
	Redis     *redis.Client
	Log       *slog.Logger

	locks       sync.Map // room_id -> *sync.Mutex
	expiryMu    sync.Mutex
	expiryTimer map[string]*time.Timer
}

func (s *Service) logger(ctx context.Context) *slog.Logger { return httpx.LoggerFrom(ctx) }

// roomLock serializes room-level changes per room inside this process and across Go
// instances (short Redis lock). Python keeps its own in-process lock; both converge
// through compare-and-write on the same Redis key.
func (s *Service) roomLock(ctx context.Context, roomID string) func() {
	value, _ := s.locks.LoadOrStore(roomID, &sync.Mutex{})
	mu := value.(*sync.Mutex)
	mu.Lock()
	key := "brseai:v1:go:room-lock:" + roomID
	token := platform.RandomHex(16)
	deadline := time.Now().Add(5 * time.Second)
	acquired := false
	for time.Now().Before(deadline) {
		ok, err := s.Redis.SetNX(ctx, key, token, 10*time.Second).Result()
		if err != nil || ok {
			acquired = ok
			break
		}
		select {
		case <-time.After(50 * time.Millisecond):
		case <-ctx.Done():
			deadline = time.Now()
		}
	}
	return func() {
		if acquired {
			_ = releaseScript.Run(context.WithoutCancel(ctx), s.Redis, []string{key}, token).Err()
		}
		mu.Unlock()
	}
}

var releaseScript = redis.NewScript(`if redis.call("get", KEYS[1]) == ARGV[1] then return redis.call("del", KEYS[1]) else return 0 end`)

// Publish sends an event envelope on the gateway control channel: WebSocket fan-out
// (Go and Python gateways) and the Python AI interpreter both listen there.
func (s *Service) Publish(ctx context.Context, eventType, roomID string, payload any) error {
	envelope := map[string]any{
		"type":     eventType,
		"event_id": "evt_" + platform.RandomHex(12),
		"room_id":  roomID,
		"sent_at":  platform.NowStr(),
		"payload":  payload,
	}
	raw, err := json.Marshal(envelope)
	if err != nil {
		return err
	}
	return s.Redis.Publish(ctx, s.Cfg.RedisChannelGatewayControl, raw).Err()
}

func (s *Service) audit(ctx context.Context, action, roomID string, fields ...any) {
	attrs := append([]any{"event", "room_audit", "action", action, "room_id", roomID}, fields...)
	s.logger(ctx).Info("room_audit", attrs...)
}

func (s *Service) expiresAt() string {
	return platform.ISO(platform.NowUTC().Add(time.Duration(s.Cfg.RoomMeetingDurationSeconds) * time.Second))
}

func (s *Service) tokenExpiresAt() string {
	return platform.ISO(platform.NowUTC().Add(time.Duration(s.Cfg.RoomTokenTTLSeconds) * time.Second))
}

func isExpired(expiresAt string) bool {
	t := platform.ParseTime(expiresAt)
	return t != nil && !platform.NowUTC().Before(*t)
}

func joinURL(base, path string) string {
	return strings.TrimRight(base, "/") + "/" + strings.TrimLeft(path, "/")
}

func (s *Service) publicAppURL(path string) string { return joinURL(s.Cfg.PublicAppURL, path) }

func (s *Service) publicGatewayWSURL(path string) string {
	base := s.Cfg.PublicGatewayWSURL
	if base == "" {
		gateway := s.Cfg.PublicGatewayURL
		scheme := "ws"
		if strings.HasPrefix(gateway, "https://") {
			scheme = "wss"
		}
		rest := gateway
		if i := strings.Index(rest, "://"); i >= 0 {
			rest = rest[i+3:]
		}
		// urlunsplit((scheme, netloc, path, "", "")) drops query and fragment.
		if i := strings.IndexAny(rest, "?#"); i >= 0 {
			rest = rest[:i]
		}
		base = scheme + "://" + rest
	}
	return joinURL(base, path)
}

func roomLanguages(room *models.RoomState) []string {
	if len(room.RoomLanguages) > 0 {
		return room.RoomLanguages
	}
	if len(room.MeetingLanguages) > 0 {
		return room.MeetingLanguages
	}
	return models.DefaultRoomLanguages
}

func invalidRoomLanguage(langs []string) *InvalidLanguageError {
	return &InvalidLanguageError{
		Message: "language must be one of room_languages: " + strings.Join(langs, ", "),
		Details: map[string]any{"field": "language", "room_languages": langs, "meeting_languages": langs},
	}
}

// ── Roles ─────────────────────────────────────────────────────────────────

func (s *Service) permissionsEnforced() bool { return s.Cfg.UserAuthRequired }

// RolesEnforced: roles apply to rooms created by a signed-in user.
func (s *Service) RolesEnforced(ctx context.Context, roomID string) bool {
	if !s.permissionsEnforced() {
		return false
	}
	room, err := s.Store.GetRoomState(ctx, roomID)
	return err == nil && room != nil && room.RolesEnabled
}

// ParticipantRole returns (user_id, role); unknown or removed users are participants.
func (s *Service) ParticipantRole(ctx context.Context, roomID, participantID string) (string, string) {
	userID, _ := s.Members.UserForParticipant(ctx, roomID, participantID)
	member, _ := s.Members.Get(ctx, roomID, userID)
	if member == nil || str(member["removed_at"]) != "" {
		return userID, models.RoleParticipant
	}
	return userID, str(member["role"])
}

func (s *Service) IsRemovedParticipant(ctx context.Context, roomID, participantID string) bool {
	userID, _ := s.Members.UserForParticipant(ctx, roomID, participantID)
	member, _ := s.Members.Get(ctx, roomID, userID)
	return member != nil && str(member["removed_at"]) != ""
}

// RequirePermission is the single authorization check for room management.
func (s *Service) RequirePermission(ctx context.Context, roomID, participantID, permission string) (string, string, error) {
	userID, role := s.ParticipantRole(ctx, roomID, participantID)
	if !HasPermission(role, permission, s.RolesEnforced(ctx, roomID)) {
		s.audit(ctx, "permission_denied", roomID, "actor", participantID, "permission", permission, "role", role)
		return userID, role, ErrPermissionDenied()
	}
	return userID, role, nil
}

func (s *Service) activeActor(ctx context.Context, roomID, participantID, sessionID string) (*models.ParticipantState, error) {
	actor, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil {
		return nil, err
	}
	if actor == nil || actor.Status == "disconnected" || actor.IsVirtual {
		return nil, &PermissionError{Code: "not_in_room", Message: "Join the meeting to manage it."}
	}
	if sessionID != "" && actor.SessionID != sessionID {
		return nil, &ActionError{Status: 409, Code: "session_mismatch", Message: "Session no longer valid for participant"}
	}
	return actor, nil
}

type PermissionsResponse struct {
	RoomID        string             `json:"room_id"`
	ParticipantID string             `json:"participant_id"`
	Role          string             `json:"role"`
	Enforced      bool               `json:"enforced"`
	Permissions   OrderedPermissions `json:"permissions"`
}

func (s *Service) GetPermissions(ctx context.Context, roomID, participantID, sessionID string) (*PermissionsResponse, error) {
	room, err := s.Store.GetRoomState(ctx, roomID)
	if err != nil {
		return nil, err
	}
	if room == nil {
		return nil, ErrRoomNotFound
	}
	if _, err := s.activeActor(ctx, roomID, participantID, sessionID); err != nil {
		return nil, err
	}
	_, role := s.ParticipantRole(ctx, roomID, participantID)
	enforced := s.RolesEnforced(ctx, roomID)
	return &PermissionsResponse{RoomID: roomID, ParticipantID: participantID, Role: role, Enforced: enforced, Permissions: Capabilities(role, enforced)}, nil
}

func (s *Service) liveRoom(ctx context.Context, roomID string) (*store.Snapshot, error) {
	snapshot, err := s.Store.GetRoomSnapshot(ctx, roomID, false)
	if err != nil {
		return nil, err
	}
	if snapshot == nil {
		return nil, ErrRoomNotFound
	}
	if isExpired(snapshot.Room.ExpiresAt) {
		return nil, ErrRoomExpired
	}
	return snapshot, nil
}

func describe(err error) string {
	if err == nil {
		return ""
	}
	return fmt.Sprint(err)
}
