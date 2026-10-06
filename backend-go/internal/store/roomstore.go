// Package store holds the Redis room state shared with the Python gateway and the
// Python AI interpreter (BE/server/service/gateway/room_store.py). Keys, TTLs and
// JSON shapes are identical so either backend can serve a room.
package store

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"time"

	"github.com/redis/go-redis/v9"

	"meetq/backend-go/internal/models"
)

const (
	TranscriptLimit = 50
	ChatLimit       = 100
)

type RoomStore struct {
	R   *redis.Client
	TTL time.Duration
}

func NewRoomStore(r *redis.Client, ttl time.Duration) *RoomStore {
	return &RoomStore{R: r, TTL: ttl}
}

func MetaKey(roomID string) string         { return "room:" + roomID + ":meta" }
func ParticipantsKey(roomID string) string { return "room:" + roomID + ":participants" }
func TranscriptsKey(roomID string) string  { return "room:" + roomID + ":transcripts" }
func ChatKey(roomID string) string         { return "room:" + roomID + ":chat" }
func AccessKey(roomID string) string       { return "room:" + roomID + ":access" }
func MembersKey(roomID string) string      { return "room:" + roomID + ":members" }
func ParticipantUsersKey(roomID string) string {
	return "room:" + roomID + ":pusers"
}

func (s *RoomStore) refreshTTL(ctx context.Context, roomID string) error {
	pipe := s.R.Pipeline()
	for _, key := range []string{MetaKey(roomID), ParticipantsKey(roomID), TranscriptsKey(roomID), ChatKey(roomID), AccessKey(roomID), MembersKey(roomID), ParticipantUsersKey(roomID)} {
		pipe.Expire(ctx, key, s.TTL)
	}
	_, err := pipe.Exec(ctx)
	return err
}

func (s *RoomStore) CreateRoom(ctx context.Context, room *models.RoomState) error {
	raw, err := json.Marshal(room)
	if err != nil {
		return err
	}
	return s.R.Set(ctx, MetaKey(room.RoomID), raw, s.TTL).Err()
}

// UpdateRoom applies a dict-style patch (Python: room_data.update(patch); RoomState(**data)).
func (s *RoomStore) UpdateRoom(ctx context.Context, roomID string, patch map[string]any) (*models.RoomState, error) {
	raw, err := s.R.Get(ctx, MetaKey(roomID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, err
	}
	for k, v := range patch {
		data[k] = jsonValue(v)
	}
	room, err := models.RoomStateFromMap(data)
	if err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(room)
	if err != nil {
		return nil, err
	}
	if err := s.R.Set(ctx, MetaKey(roomID), encoded, s.TTL).Err(); err != nil {
		return nil, err
	}
	return room, s.refreshTTL(ctx, roomID)
}

// jsonValue round-trips structs through JSON so they merge like Python dicts.
func jsonValue(v any) any {
	switch v.(type) {
	case nil, string, bool, int, float64, []string, map[string]any, []any:
		return v
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return v
	}
	var out any
	_ = json.Unmarshal(raw, &out)
	return out
}

func (s *RoomStore) GetRoomState(ctx context.Context, roomID string) (*models.RoomState, error) {
	raw, err := s.R.Get(ctx, MetaKey(roomID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return models.DecodeRoomState(raw)
}

func (s *RoomStore) RoomExists(ctx context.Context, roomID string) (bool, error) {
	n, err := s.R.Exists(ctx, MetaKey(roomID)).Result()
	return n > 0, err
}

type Snapshot struct {
	Room              models.SnapshotRoom          `json:"room"`
	Participants      []models.ParticipantSnapshot `json:"participants"`
	RecentTranscripts []models.Transcript          `json:"recent_transcripts"`
	RecentMessages    []models.ChatMessage         `json:"recent_messages"`
	// State is the full room state (not serialized).
	State *models.RoomState `json:"-"`
}

// AllParticipants returns every stored participant (including disconnected ones), in join order.
func (s *RoomStore) AllParticipants(ctx context.Context, roomID string) ([]*models.ParticipantState, error) {
	data, err := s.R.HGetAll(ctx, ParticipantsKey(roomID)).Result()
	if err != nil {
		return nil, err
	}
	out := make([]*models.ParticipantState, 0, len(data))
	for _, raw := range data {
		p, err := models.DecodeParticipant([]byte(raw))
		if err != nil {
			continue
		}
		out = append(out, p)
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].JoinedAt != out[j].JoinedAt {
			return out[i].JoinedAt < out[j].JoinedAt
		}
		return out[i].ParticipantID < out[j].ParticipantID
	})
	return out, nil
}

func (s *RoomStore) GetRoomSnapshot(ctx context.Context, roomID string, includeSilentTranscripts bool) (*Snapshot, error) {
	room, err := s.GetRoomState(ctx, roomID)
	if err != nil || room == nil {
		return nil, err
	}
	stored, err := s.AllParticipants(ctx, roomID)
	if err != nil {
		return nil, err
	}
	participants := []models.ParticipantSnapshot{}
	for _, p := range stored {
		if p.Status == "disconnected" {
			continue
		}
		participants = append(participants, p.Snapshot())
	}
	if room.BrseEnabled {
		participants = append(participants, room.VirtualParticipants...)
	}
	count := models.ActiveHumanCount(participants)
	var hostID *string
	for _, p := range participants {
		if p.Role == models.RoleHost && !p.IsVirtual {
			id := p.ParticipantID
			hostID = &id
			break
		}
	}
	transcripts := []models.Transcript{}
	rawTranscripts, err := s.R.LRange(ctx, TranscriptsKey(roomID), 0, -1).Result()
	if err != nil {
		return nil, err
	}
	for _, raw := range rawTranscripts {
		if t, err := models.DecodeTranscript([]byte(raw)); err == nil {
			transcripts = append(transcripts, t)
		}
	}
	if !includeSilentTranscripts && (!room.BrseEnabled || room.BrseMode == models.BrseModeSilentSummary) {
		transcripts = []models.Transcript{}
	}
	messages := []models.ChatMessage{}
	rawChat, err := s.R.LRange(ctx, ChatKey(roomID), 0, -1).Result()
	if err != nil {
		return nil, err
	}
	for _, raw := range rawChat {
		if m, err := models.DecodeChat([]byte(raw)); err == nil {
			messages = append(messages, *m)
		}
	}
	return &Snapshot{
		Room: models.SnapshotRoom{
			RoomResponse:      room.Response(),
			ParticipantCount:  count,
			HostParticipantID: hostID,
		},
		Participants:      participants,
		RecentTranscripts: transcripts,
		RecentMessages:    messages,
		State:             room,
	}, nil
}

func (s *RoomStore) AddParticipant(ctx context.Context, roomID string, p *models.ParticipantState) error {
	raw, err := json.Marshal(p)
	if err != nil {
		return err
	}
	if err := s.R.HSet(ctx, ParticipantsKey(roomID), p.ParticipantID, raw).Err(); err != nil {
		return err
	}
	return s.refreshTTL(ctx, roomID)
}

func (s *RoomStore) GetParticipant(ctx context.Context, roomID, participantID string) (*models.ParticipantState, error) {
	if participantID == "" {
		return nil, nil
	}
	raw, err := s.R.HGet(ctx, ParticipantsKey(roomID), participantID).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return models.DecodeParticipant(raw)
}

// UpdateParticipant applies a dict-style patch; missing participants are ignored (Python behaviour).
func (s *RoomStore) UpdateParticipant(ctx context.Context, roomID, participantID string, patch map[string]any) error {
	raw, err := s.R.HGet(ctx, ParticipantsKey(roomID), participantID).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil
	}
	if err != nil {
		return err
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return err
	}
	for k, v := range patch {
		data[k] = jsonValue(v)
	}
	merged, err := json.Marshal(data)
	if err != nil {
		return err
	}
	p, err := models.DecodeParticipant(merged)
	if err != nil {
		return err
	}
	encoded, err := json.Marshal(p)
	if err != nil {
		return err
	}
	if err := s.R.HSet(ctx, ParticipantsKey(roomID), participantID, encoded).Err(); err != nil {
		return err
	}
	return s.refreshTTL(ctx, roomID)
}

func (s *RoomStore) RemoveParticipant(ctx context.Context, roomID, participantID string) error {
	if err := s.R.HDel(ctx, ParticipantsKey(roomID), participantID).Err(); err != nil {
		return err
	}
	return s.refreshTTL(ctx, roomID)
}

func (s *RoomStore) AppendChat(ctx context.Context, roomID string, m *models.ChatMessage) error {
	raw, err := json.Marshal(m)
	if err != nil {
		return err
	}
	pipe := s.R.Pipeline()
	pipe.RPush(ctx, ChatKey(roomID), raw)
	pipe.LTrim(ctx, ChatKey(roomID), -ChatLimit, -1)
	if _, err := pipe.Exec(ctx); err != nil {
		return err
	}
	return s.refreshTTL(ctx, roomID)
}

func (s *RoomStore) AppendTranscript(ctx context.Context, roomID string, raw []byte) error {
	pipe := s.R.Pipeline()
	pipe.RPush(ctx, TranscriptsKey(roomID), raw)
	pipe.LTrim(ctx, TranscriptsKey(roomID), -TranscriptLimit, -1)
	if _, err := pipe.Exec(ctx); err != nil {
		return err
	}
	return s.refreshTTL(ctx, roomID)
}

func (s *RoomStore) ClearTranscripts(ctx context.Context, roomID string) error {
	if err := s.R.Del(ctx, TranscriptsKey(roomID)).Err(); err != nil {
		return err
	}
	return s.refreshTTL(ctx, roomID)
}

// MarkRoomEmpty mirrors mark_room_empty (keeps the key TTL untouched except via SET ex).
func (s *RoomStore) MarkRoomEmpty(ctx context.Context, roomID, emptiedAt string) error {
	raw, err := s.R.Get(ctx, MetaKey(roomID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil
	}
	if err != nil {
		return err
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return err
	}
	data["state"] = "empty"
	if emptiedAt != "" {
		data["emptied_at"] = emptiedAt
	}
	room, err := models.RoomStateFromMap(data)
	if err != nil {
		return err
	}
	encoded, _ := json.Marshal(room)
	return s.R.Set(ctx, MetaKey(roomID), encoded, s.TTL).Err()
}

// ActivateRoom mirrors the join path that flips created/empty rooms to active.
func (s *RoomStore) ActivateRoom(ctx context.Context, roomID, now string) error {
	raw, err := s.R.Get(ctx, MetaKey(roomID)).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil
	}
	if err != nil {
		return err
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return err
	}
	data["state"] = "active"
	if v, _ := data["activated_at"].(string); v == "" {
		data["activated_at"] = now
	}
	data["emptied_at"] = nil
	room, err := models.RoomStateFromMap(data)
	if err != nil {
		return err
	}
	return s.CreateRoom(ctx, room)
}

func (s *RoomStore) DeleteRoom(ctx context.Context, roomID string) error {
	return s.R.Del(ctx, MetaKey(roomID), ParticipantsKey(roomID), TranscriptsKey(roomID), ChatKey(roomID), AccessKey(roomID), MembersKey(roomID), ParticipantUsersKey(roomID)).Err()
}
