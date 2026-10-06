// Package history writes the MongoDB meeting history exactly like the Python gateway
// (BE/server/service/persistence/room_history.py): same collections, same document
// shapes (string timestamps plus *_dt dates), same upsert semantics. Indexes and
// one-time migrations stay owned by the Python service (ensure_indexes at startup).
//
// AI outputs (transcripts, relay, summaries) are written by the Python AI service.
package history

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
)

const (
	Rooms        = "rooms"
	Participants = "room_participants"
	Messages     = "room_messages"
	Summaries    = "meeting_summaries"
	Memberships  = "room_memberships"
	Settings     = "system_settings"
	Users        = "users"
)

type Repository struct {
	DB      *mongo.Database
	Timeout time.Duration
	Log     *slog.Logger
}

func (r *Repository) Enabled() bool { return r != nil && r.DB != nil }

func (r *Repository) col(name string) *mongo.Collection { return r.DB.Collection(name) }

// Schedule runs a persistence operation detached from the request (Python:
// room_history.schedule): failures are logged, never surfaced to the caller.
func (r *Repository) Schedule(ctx context.Context, action, roomID string, op func(context.Context) error) {
	if !r.Enabled() {
		return
	}
	detached := context.WithoutCancel(ctx)
	go func() {
		c, cancel := context.WithTimeout(detached, r.timeout())
		defer cancel()
		if err := op(c); err != nil {
			r.logger().Error("mongodb persistence failed", "action", action, "room_id", roomID, "error", err.Error())
		}
	}()
}

func (r *Repository) timeout() time.Duration {
	if r.Timeout <= 0 {
		return 15 * time.Second
	}
	return r.Timeout
}

func (r *Repository) logger() *slog.Logger {
	if r.Log != nil {
		return r.Log
	}
	return slog.Default()
}

// dt mirrors `_parse_dt`: a BSON date or nil.
func dt(value *string) any {
	if value == nil {
		return nil
	}
	if t := platform.ParseTime(*value); t != nil {
		return *t
	}
	return nil
}

func dtStr(value string) any {
	if value == "" {
		return nil
	}
	return dt(&value)
}

func strOrNil(v *string) any {
	if v == nil {
		return nil
	}
	return *v
}

// ToBSONValue converts a JSON-tagged struct to plain maps (keeping integers as int64),
// matching how pydantic's model_dump() lands in Mongo.
func ToBSONValue(v any) any {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	dec := json.NewDecoder(bytesReader(raw))
	dec.UseNumber()
	var out any
	if err := dec.Decode(&out); err != nil {
		return nil
	}
	return fixNumbers(out)
}

func fixNumbers(v any) any {
	switch t := v.(type) {
	case map[string]any:
		for k, item := range t {
			t[k] = fixNumbers(item)
		}
		return t
	case []any:
		for i, item := range t {
			t[i] = fixNumbers(item)
		}
		return t
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return i
		}
		f, _ := t.Float64()
		return f
	}
	return v
}

// roomDoc mirrors `_room_doc_from_state`.
func roomDoc(room *models.RoomState, updatedAt string) bson.M {
	langs := room.RoomLanguages
	if langs == nil {
		langs = room.MeetingLanguages
	}
	if langs == nil {
		langs = []string{}
	}
	meeting := room.MeetingLanguages
	if len(meeting) == 0 {
		meeting = langs
	}
	virtual := []any{}
	for _, p := range room.VirtualParticipants {
		virtual = append(virtual, ToBSONValue(p))
	}
	return bson.M{
		"room_id":              room.RoomID,
		"state":                room.State,
		"created_at":           room.CreatedAt,
		"created_at_dt":        dtStr(room.CreatedAt),
		"activated_at":         strOrNil(room.ActivatedAt),
		"activated_at_dt":      dt(room.ActivatedAt),
		"emptied_at":           strOrNil(room.EmptiedAt),
		"emptied_at_dt":        dt(room.EmptiedAt),
		"expires_at":           room.ExpiresAt,
		"expires_at_dt":        dtStr(room.ExpiresAt),
		"ended_at":             nil,
		"ended_at_dt":          nil,
		"room_languages":       langs,
		"meeting_languages":    meeting,
		"brse_enabled":         room.BrseEnabled,
		"brse_mode":            room.BrseMode,
		"brse_output_mode":     room.BrseOutputMode,
		"meeting_mode":         room.MeetingMode,
		"interpreter_mode":     room.InterpreterMode,
		"audio_routing":        ToBSONValue(room.AudioRouting),
		"password_required":    room.PasswordRequired,
		"title":                strOrNil(room.Title),
		"locked":               room.Locked,
		"virtual_participants": virtual,
		"updated_at":           updatedAt,
		"updated_at_dt":        dtStr(updatedAt),
	}
}

func without(doc bson.M, keys ...string) bson.M {
	out := bson.M{}
	for k, v := range doc {
		skip := false
		for _, key := range keys {
			if k == key {
				skip = true
			}
		}
		if !skip {
			out[k] = v
		}
	}
	return out
}

var upsert = options.UpdateOne().SetUpsert(true)

// PersistRoomCreated mirrors persist_room_created (+ creator membership).
func (r *Repository) PersistRoomCreated(ctx context.Context, room *models.RoomState, shareURL string, createdBy string) error {
	now := platform.NowStr()
	doc := roomDoc(room, now)
	if createdBy != "" {
		doc["created_by_user_id"] = createdBy
	}
	doc["history_sort_at_dt"] = dtStr(room.CreatedAt)
	doc["activated_at"] = strOrNil(room.ActivatedAt)
	doc["emptied_at"] = strOrNil(room.EmptiedAt)
	doc["ended_at"] = nil
	doc["duration_seconds"] = nil
	doc["participant_count_current"] = 0
	doc["participant_count_total"] = 0
	doc["participant_ids"] = []any{}
	doc["participant_summaries"] = []any{}
	doc["status_summary"] = bson.M{"state": room.State, "terminal": false, "reason": nil}
	doc["share_url"] = shareURL
	update := bson.M{
		"$setOnInsert": bson.M{"room_id": room.RoomID, "created_by": "gateway"},
		"$set":         without(doc, "room_id"),
	}
	if createdBy != "" {
		update["$addToSet"] = bson.M{"member_user_ids": createdBy}
	}
	if _, err := r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": room.RoomID}, update, upsert); err != nil {
		return err
	}
	if createdBy != "" {
		if err := r.PersistMembership(ctx, room.RoomID, createdBy, MembershipFields{Role: models.RoleHost, IsCreator: true}); err != nil {
			return err
		}
	}
	for _, p := range room.VirtualParticipants {
		if err := r.PersistParticipantJoin(ctx, room, participantFromSnapshot(p), 0, nil, ""); err != nil {
			return err
		}
	}
	return nil
}

// PersistRoomModeUpdated mirrors persist_room_mode_updated.
func (r *Repository) PersistRoomModeUpdated(ctx context.Context, room *models.RoomState, changedAt string) error {
	doc := roomDoc(room, platform.NowStr())
	doc["status_summary"] = bson.M{"state": nonEmpty(room.State, "active"), "terminal": false, "reason": "brse_updated"}
	doc["last_event_at"] = changedAt
	_, err := r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": room.RoomID}, bson.M{
		"$setOnInsert": bson.M{"room_id": room.RoomID, "created_by": "gateway"},
		"$set":         without(doc, "room_id"),
	}, upsert)
	return err
}

func nonEmpty(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

// JoinParticipant is the subset of a participant the history needs.
type JoinParticipant struct {
	ParticipantID   string
	SessionID       *string
	DisplayName     string
	Language        string
	Kind            string
	IsVirtual       bool
	LiveKitIdentity *string
	Metadata        map[string]any
	JoinedAt        *string
	LastSeenAt      *string
	Status          string
}

func participantFromSnapshot(p models.ParticipantSnapshot) JoinParticipant {
	return JoinParticipant{
		ParticipantID: p.ParticipantID, DisplayName: p.DisplayName, Language: p.Language, Kind: p.Kind,
		IsVirtual: p.IsVirtual, LiveKitIdentity: p.LiveKitIdentity, Metadata: p.Metadata, JoinedAt: p.JoinedAt,
		LastSeenAt: p.LastSeenAt, Status: p.Status,
	}
}

func ParticipantFromState(p *models.ParticipantState) JoinParticipant {
	joined := p.JoinedAt
	session := p.SessionID
	return JoinParticipant{
		ParticipantID: p.ParticipantID, SessionID: &session, DisplayName: p.DisplayName, Language: p.Language,
		Kind: p.Kind, IsVirtual: p.IsVirtual, LiveKitIdentity: p.LiveKitIdentity, Metadata: p.Metadata,
		JoinedAt: &joined, LastSeenAt: p.LastSeenAt, Status: p.Status,
	}
}

// PersistParticipantJoin mirrors persist_participant_join.
func (r *Repository) PersistParticipantJoin(ctx context.Context, room *models.RoomState, p JoinParticipant, currentHumanCount int, clientMeta any, userID string) error {
	if room == nil || p.ParticipantID == "" {
		return nil
	}
	joinedAt := platform.NowStr()
	if p.JoinedAt != nil && *p.JoinedAt != "" {
		joinedAt = *p.JoinedAt
	}
	kind := p.Kind
	if kind == "" {
		kind = models.KindHuman
		if p.IsVirtual {
			kind = models.KindVirtualBrse
		}
	}
	now := platform.NowStr()
	metadata := p.Metadata
	if metadata == nil {
		metadata = map[string]any{}
	}
	lastSeen := joinedAt
	if p.LastSeenAt != nil && *p.LastSeenAt != "" {
		lastSeen = *p.LastSeenAt
	}
	set := bson.M{
		"room_id":           room.RoomID,
		"participant_id":    p.ParticipantID,
		"display_name":      p.DisplayName,
		"language":          p.Language,
		"kind":              kind,
		"is_virtual":        p.IsVirtual,
		"livekit_identity":  strOrNil(p.LiveKitIdentity),
		"metadata":          ToBSONValue(metadata),
		"last_joined_at":    joinedAt,
		"last_joined_at_dt": dtStr(joinedAt),
		"last_seen_at":      lastSeen,
		"updated_at":        now,
		"updated_at_dt":     dtStr(now),
	}
	if userID != "" {
		set["user_id"] = userID
	}
	status := p.Status
	if status == "" {
		status = "connected"
	}
	session := bson.M{
		"session_id":   strOrNil(p.SessionID),
		"joined_at":    joinedAt,
		"joined_at_dt": dtStr(joinedAt),
		"left_at":      nil,
		"left_at_dt":   nil,
		"status":       status,
		"client":       ToBSONValue(clientMeta),
	}
	_, err := r.col(Participants).UpdateOne(ctx, bson.M{"room_id": room.RoomID, "participant_id": p.ParticipantID}, bson.M{
		"$setOnInsert": bson.M{"first_joined_at": joinedAt, "first_joined_at_dt": dtStr(joinedAt), "created_at": now, "created_at_dt": dtStr(now)},
		"$set":         set,
		"$inc":         bson.M{"join_count": 1},
		"$push":        bson.M{"sessions": session},
	}, upsert)
	if err != nil {
		return err
	}
	return r.refreshParticipantSummary(ctx, room, currentHumanCount, !p.IsVirtual)
}

// refreshParticipantSummary mirrors _refresh_room_participant_summary.
func (r *Repository) refreshParticipantSummary(ctx context.Context, room *models.RoomState, currentHumanCount int, clearTerminal bool) error {
	projection := options.Find().SetProjection(bson.M{
		"_id": 0, "participant_id": 1, "display_name": 1, "language": 1, "kind": 1, "is_virtual": 1,
		"first_joined_at": 1, "last_joined_at": 1, "last_left_at": 1, "join_count": 1,
	})
	cursor, err := r.col(Participants).Find(ctx, bson.M{"room_id": room.RoomID, "is_virtual": bson.M{"$ne": true}}, projection)
	if err != nil {
		return err
	}
	var docs []bson.M
	if err := cursor.All(ctx, &docs); err != nil {
		return err
	}
	ids := []any{}
	summaries := []any{}
	for _, doc := range docs {
		if id, ok := doc["participant_id"].(string); ok && id != "" {
			ids = append(ids, id)
		}
		summaries = append(summaries, doc)
	}
	now := platform.NowStr()
	update := roomDoc(room, now)
	update["participant_count_current"] = currentHumanCount
	update["participant_count_total"] = len(ids)
	update["participant_ids"] = ids
	update["participant_summaries"] = summaries
	update["last_event_at"] = now
	if clearTerminal {
		sortAt := dt(room.ActivatedAt)
		if sortAt == nil {
			sortAt = dtStr(room.CreatedAt)
		}
		update["state"] = "active"
		update["ended_at"] = nil
		update["history_sort_at_dt"] = sortAt
		update["duration_seconds"] = nil
		update["status_summary"] = bson.M{"state": "active", "terminal": false, "reason": nil}
		if room.ActivatedAt == nil || *room.ActivatedAt == "" {
			activated := platform.NowStr()
			update["activated_at"] = activated
			update["activated_at_dt"] = dtStr(activated)
		}
	}
	_, err = r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": room.RoomID}, bson.M{
		"$setOnInsert": bson.M{"room_id": room.RoomID, "created_by": "gateway"},
		"$set":         without(update, "room_id"),
	}, upsert)
	return err
}

// PersistParticipantLeft mirrors persist_participant_left.
func (r *Repository) PersistParticipantLeft(ctx context.Context, roomID string, p *models.ParticipantState, leftAt, reason string, currentHumanCount int, terminalState string) error {
	now := platform.NowStr()
	set := bson.M{
		"last_left_at":    leftAt,
		"last_left_at_dt": dtStr(leftAt),
		"last_seen_at":    leftAt,
		"updated_at":      now,
		"updated_at_dt":   dtStr(now),
	}
	opts := options.UpdateOne()
	if p.SessionID != "" {
		set["sessions.$[session].left_at"] = leftAt
		set["sessions.$[session].left_at_dt"] = dtStr(leftAt)
		set["sessions.$[session].status"] = "disconnected"
		set["sessions.$[session].reason"] = reason
		opts.SetArrayFilters([]any{bson.M{"session.session_id": p.SessionID, "session.left_at": nil}})
	}
	if _, err := r.col(Participants).UpdateOne(ctx, bson.M{"room_id": roomID, "participant_id": p.ParticipantID}, bson.M{"$set": set}, opts); err != nil {
		return err
	}
	state := "active"
	var endedAt, endReason *string
	terminal := terminalState != ""
	if terminal {
		state = terminalState
		endedAt = &leftAt
		endReason = &reason
	}
	return r.updateLifecycle(ctx, roomID, state, endedAt, endReason, currentHumanCount, terminal)
}

// PersistRoomExpired mirrors persist_room_expired.
func (r *Repository) PersistRoomExpired(ctx context.Context, room *models.RoomState, roomID, expiredAt string, currentHumanCount int, reason string) error {
	var existing bson.M
	err := r.col(Rooms).FindOne(ctx, bson.M{"room_id": roomID}, options.FindOne().SetProjection(bson.M{"_id": 0, "ended_at": 1, "status_summary": 1})).Decode(&existing)
	if err == nil && existing["ended_at"] != nil {
		if summary, ok := existing["status_summary"].(bson.M); ok && summary["terminal"] == true {
			return nil
		}
	} else if err != nil && !errors.Is(err, mongo.ErrNoDocuments) {
		return err
	}
	timestamp := expiredAt
	if timestamp == "" && room != nil {
		timestamp = room.ExpiresAt
	}
	if timestamp == "" {
		timestamp = platform.NowStr()
	}
	return r.updateLifecycle(ctx, roomID, "expired", &timestamp, &reason, currentHumanCount, true)
}

// PersistRoomEmptied mirrors persist_room_emptied.
func (r *Repository) PersistRoomEmptied(ctx context.Context, roomID, emptiedAt string, currentHumanCount int, reason string) error {
	if emptiedAt == "" {
		emptiedAt = platform.NowStr()
	}
	return r.updateLifecycle(ctx, roomID, "empty", &emptiedAt, &reason, currentHumanCount, true)
}

// updateLifecycle mirrors _update_room_lifecycle_summary.
func (r *Repository) updateLifecycle(ctx context.Context, roomID, state string, endedAt, reason *string, currentHumanCount int, terminal bool) error {
	if terminal && endedAt != nil {
		var current bson.M
		err := r.col(Rooms).FindOne(ctx, bson.M{"room_id": roomID}, options.FindOne().SetProjection(bson.M{"_id": 0, "last_event_at": 1})).Decode(&current)
		if err == nil {
			if last, ok := current["last_event_at"].(string); ok {
				currentAt := platform.ParseTime(last)
				nextAt := platform.ParseTime(*endedAt)
				if currentAt != nil && nextAt != nil && currentAt.After(*nextAt) {
					return nil
				}
			}
		}
	}
	lastEvent := platform.NowStr()
	if endedAt != nil && *endedAt != "" {
		lastEvent = *endedAt
	}
	set := bson.M{
		"state":                     state,
		"ended_at":                  strOrNil(endedAt),
		"ended_at_dt":               dt(endedAt),
		"participant_count_current": currentHumanCount,
		"status_summary":            bson.M{"state": state, "terminal": terminal, "reason": strOrNil(reason)},
		"last_event_at":             lastEvent,
		"updated_at":                platform.NowStr(),
	}
	if terminal && endedAt != nil {
		set["history_sort_at_dt"] = dt(endedAt)
	}
	var updated bson.M
	err := r.col(Rooms).FindOneAndUpdate(ctx, bson.M{"room_id": roomID}, bson.M{
		"$setOnInsert": bson.M{"room_id": roomID, "created_by": "gateway"},
		"$set":         set,
	}, options.FindOneAndUpdate().SetUpsert(true).SetReturnDocument(options.After)).Decode(&updated)
	if err != nil {
		return err
	}
	activated, _ := updated["activated_at"].(string)
	if activated == "" {
		activated, _ = updated["created_at"].(string)
	}
	if endedAt != nil {
		start := platform.ParseTime(activated)
		end := platform.ParseTime(*endedAt)
		if start != nil && end != nil {
			duration := int(end.Sub(*start).Seconds())
			if duration < 0 {
				duration = 0
			}
			_, err = r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": roomID}, bson.M{"$set": bson.M{"duration_seconds": duration}})
			return err
		}
	}
	return nil
}

// PersistChat mirrors persist_chat_message.
func (r *Repository) PersistChat(ctx context.Context, m *models.ChatMessage, withRoomCounters bool) error {
	createdAt := m.CreatedAt
	if createdAt == "" {
		createdAt = platform.NowStr()
	}
	translations := []any{}
	for _, t := range m.Translations {
		translations = append(translations, bson.M{"language": t.Language, "text": t.Text})
	}
	doc := bson.M{
		"room_id":           m.RoomID,
		"message_id":        m.MessageID,
		"conversation_type": "chat",
		"kind":              "chat",
		"participant_id":    m.ParticipantID,
		"display_name":      m.DisplayName,
		"language":          m.Language,
		"text":              m.Text,
		"created_at":        createdAt,
		"created_at_dt":     dtStr(createdAt),
		"client_event_id":   strOrNil(m.ClientEventID),
		"translation_mode":  m.TranslationMode,
		"translations":      translations,
		"metadata": bson.M{
			"sender_id":           strOrNil(m.SenderID),
			"sender_display_name": strOrNil(m.SenderDisplayName),
			"sender_language":     strOrNil(m.SenderLanguage),
			"sent_at":             strOrNil(m.SentAt),
		},
	}
	result, err := r.col(Messages).UpdateOne(ctx, bson.M{"room_id": m.RoomID, "message_id": m.MessageID, "kind": "chat"}, bson.M{"$setOnInsert": doc}, upsert)
	if err != nil {
		return err
	}
	if withRoomCounters && result.UpsertedID != nil {
		_, err = r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": m.RoomID}, bson.M{
			"$setOnInsert": bson.M{"room_id": m.RoomID, "created_by": "gateway"},
			"$set":         bson.M{"last_message_at": createdAt, "last_event_at": createdAt, "updated_at": platform.NowStr()},
			"$inc":         bson.M{"message_count": 1, "chat_message_count": 1},
		}, upsert)
	}
	return err
}

type MembershipFields struct {
	Role        string
	DisplayName string
	Language    string
	JoinedAt    string
	IsCreator   bool
}

// PersistMembership mirrors persist_membership.
func (r *Repository) PersistMembership(ctx context.Context, roomID, userID string, f MembershipFields) error {
	now := platform.NowStr()
	set := bson.M{"updated_at": now, "updated_at_dt": dtStr(now)}
	if f.Role != "" {
		set["role"] = f.Role
	}
	if f.DisplayName != "" {
		set["display_name"] = f.DisplayName
	}
	if f.Language != "" {
		set["language"] = f.Language
	}
	if f.JoinedAt != "" {
		set["last_joined_at"] = f.JoinedAt
		set["last_joined_at_dt"] = dtStr(f.JoinedAt)
		set["left_at"] = nil
		set["left_at_dt"] = nil
	}
	onInsert := bson.M{
		"room_id": roomID, "user_id": userID, "is_creator": f.IsCreator, "removed_at": nil,
		"removed_by_user_id": nil, "created_at": now, "created_at_dt": dtStr(now),
	}
	if f.Role == "" {
		onInsert["role"] = models.RoleParticipant
	}
	if _, err := r.col(Memberships).UpdateOne(ctx, bson.M{"room_id": roomID, "user_id": userID}, bson.M{"$setOnInsert": onInsert, "$set": set}, upsert); err != nil {
		return err
	}
	if f.JoinedAt != "" {
		if _, err := r.col(Memberships).UpdateOne(ctx,
			bson.M{"room_id": roomID, "user_id": userID, "first_joined_at": bson.M{"$exists": false}},
			bson.M{"$set": bson.M{"first_joined_at": f.JoinedAt, "first_joined_at_dt": dtStr(f.JoinedAt)}}); err != nil {
			return err
		}
	}
	addToSet := bson.M{"member_user_ids": userID}
	if f.JoinedAt != "" {
		addToSet["joined_user_ids"] = userID
	}
	_, err := r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": roomID}, bson.M{
		"$setOnInsert": bson.M{"room_id": roomID, "created_by": "gateway"},
		"$addToSet":    addToSet,
	}, upsert)
	return err
}

func (r *Repository) PersistMembershipLeft(ctx context.Context, roomID, userID, leftAt string) error {
	_, err := r.col(Memberships).UpdateOne(ctx, bson.M{"room_id": roomID, "user_id": userID}, bson.M{
		"$set": bson.M{"left_at": leftAt, "left_at_dt": dtStr(leftAt), "updated_at": platform.NowStr()},
	})
	return err
}

func (r *Repository) PersistMembershipRemoved(ctx context.Context, roomID, userID, removedAt, removedBy string) error {
	var by any
	if removedBy != "" {
		by = removedBy
	}
	if _, err := r.col(Memberships).UpdateOne(ctx, bson.M{"room_id": roomID, "user_id": userID}, bson.M{"$set": bson.M{
		"removed_at": removedAt, "removed_at_dt": dtStr(removedAt), "removed_by_user_id": by,
		"left_at": removedAt, "left_at_dt": dtStr(removedAt), "updated_at": platform.NowStr(),
	}}); err != nil {
		return err
	}
	_, err := r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": roomID}, bson.M{"$pull": bson.M{"member_user_ids": userID}})
	return err
}

// PersistRoomFlags sets small room facts (locked, password_required, has_recording).
func (r *Repository) PersistRoomFlags(ctx context.Context, roomID string, fields bson.M) error {
	_, err := r.col(Rooms).UpdateOne(ctx, bson.M{"room_id": roomID}, bson.M{
		"$setOnInsert": bson.M{"room_id": roomID, "created_by": "gateway"},
		"$set":         fields,
	}, upsert)
	return err
}

func (r *Repository) RoomExists(ctx context.Context, roomID string) (bool, error) {
	n, err := r.col(Rooms).CountDocuments(ctx, bson.M{"room_id": roomID}, options.Count().SetLimit(1))
	return n > 0, err
}

func (r *Repository) RoomPasswordRequired(ctx context.Context, roomID string) (bool, error) {
	var doc bson.M
	err := r.col(Rooms).FindOne(ctx, bson.M{"room_id": roomID}, options.FindOne().SetProjection(bson.M{"password_required": 1})).Decode(&doc)
	if errors.Is(err, mongo.ErrNoDocuments) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	b, _ := doc["password_required"].(bool)
	return b, nil
}

// UserJoinedRoom reports whether the user ever joined (room_participants.user_id).
func (r *Repository) UserJoinedRoom(ctx context.Context, roomID, userID string) (bool, error) {
	n, err := r.col(Participants).CountDocuments(ctx, bson.M{"room_id": roomID, "user_id": userID}, options.Count().SetLimit(1))
	return n > 0, err
}

// RememberUser mirrors auth.api._remember_user (best effort).
func (r *Repository) RememberUser(ctx context.Context, userID string, fields bson.M) error {
	now := platform.NowUTC()
	fields["last_login_at"] = now
	_, err := r.col(Users).UpdateOne(ctx, bson.M{"_id": userID}, bson.M{
		"$set":         fields,
		"$setOnInsert": bson.M{"created_at": now},
	}, upsert)
	return err
}

func bytesReader(b []byte) *bytes.Reader { return bytes.NewReader(b) }

// GetMeetingSummary mirrors get_meeting_summary (legacy final docs have no summary_type).
func (r *Repository) GetMeetingSummary(ctx context.Context, roomID, summaryType string) (map[string]any, error) {
	var doc bson.M
	err := r.col(Summaries).FindOne(ctx, bson.M{"room_id": roomID, "summary_type": summaryType}, options.FindOne().SetProjection(bson.M{"_id": 0})).Decode(&doc)
	if errors.Is(err, mongo.ErrNoDocuments) && summaryType == "final" {
		err = r.col(Summaries).FindOne(ctx, bson.M{"room_id": roomID, "summary_type": bson.M{"$exists": false}}, options.FindOne().SetProjection(bson.M{"_id": 0})).Decode(&doc)
		if err == nil {
			doc["summary_type"] = "final"
		}
	}
	if errors.Is(err, mongo.ErrNoDocuments) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return map[string]any(doc), nil
}
