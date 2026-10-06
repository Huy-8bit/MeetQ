// Package notify ports server/integrations/telegram.py (operational notifications).
package notify

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"sync"
	"time"
)

type Telegram struct {
	Enabled                 bool
	NotifyRoomCreated       bool
	NotifyParticipantJoined bool
	BotToken                string
	ChatID                  string
	APIBaseURL              string
	Timeout                 time.Duration
	Log                     *slog.Logger

	warnOnce sync.Once
}

func (t *Telegram) RoomCreatedEnabled() bool { return t != nil && t.Enabled && t.NotifyRoomCreated }
func (t *Telegram) ParticipantJoinedEnabled() bool {
	return t != nil && t.Enabled && t.NotifyParticipantJoined
}

type RoomInfo struct {
	RoomID           string
	MeetingLanguages []string
	BrseEnabled      bool
	CreatedAt        string
	ExpiresAt        string
	ParticipantLimit *int
}

type ParticipantInfo struct {
	ParticipantID string
	DisplayName   string
	Language      string
	JoinedAt      string
}

func pretty(v any) string {
	// json.dumps(..., ensure_ascii=False, indent=2)
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
	return string(bytes.TrimRight(buf.Bytes(), "\n"))
}

type ordered []struct {
	k string
	v any
}

func (o ordered) MarshalJSON() ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteByte('{')
	for i, kv := range o {
		if i > 0 {
			buf.WriteByte(',')
		}
		key, _ := json.Marshal(kv.k)
		buf.Write(key)
		buf.WriteByte(':')
		val, err := json.Marshal(kv.v)
		if err != nil {
			return nil, err
		}
		buf.Write(val)
	}
	buf.WriteByte('}')
	return buf.Bytes(), nil
}

func kv(k string, v any) struct {
	k string
	v any
} {
	return struct {
		k string
		v any
	}{k, v}
}

func (t *Telegram) RoomCreated(ctx context.Context, room RoomInfo, shareURL string) {
	if !t.RoomCreatedEnabled() {
		return
	}
	text := pretty(ordered{
		kv("event", "room.created"),
		kv("room", ordered{
			kv("room_id", room.RoomID),
			kv("meeting_languages", room.MeetingLanguages),
			kv("brse_enabled", room.BrseEnabled),
			kv("created_at", room.CreatedAt),
			kv("expires_at", room.ExpiresAt),
			kv("participant_limit", room.ParticipantLimit),
		}),
		kv("share_url", shareURL),
	})
	t.send(ctx, "room-created", room.RoomID, text)
}

func (t *Telegram) ParticipantJoined(ctx context.Context, room RoomInfo, p ParticipantInfo, count int) {
	if !t.ParticipantJoinedEnabled() {
		return
	}
	text := pretty(ordered{
		kv("event", "participant.joined"),
		kv("room", ordered{
			kv("room_id", room.RoomID),
			kv("meeting_languages", room.MeetingLanguages),
			kv("brse_enabled", room.BrseEnabled),
			kv("participant_count", count),
		}),
		kv("participant", ordered{
			kv("participant_id", p.ParticipantID),
			kv("display_name", p.DisplayName),
			kv("language", p.Language),
			kv("joined_at", p.JoinedAt),
		}),
	})
	t.send(ctx, "participant-joined", room.RoomID, text)
}

// send runs in the background; failures are logged without the bot token.
func (t *Telegram) send(ctx context.Context, kind, roomID, text string) {
	if t.BotToken == "" || t.ChatID == "" {
		t.warnOnce.Do(func() {
			t.Log.Warn("telegram notification skipped: missing bot token or chat id", "kind", kind, "room_id", roomID)
		})
		return
	}
	detached := context.WithoutCancel(ctx)
	go func() {
		c, cancel := context.WithTimeout(detached, t.Timeout)
		defer cancel()
		body, _ := json.Marshal(map[string]any{"chat_id": t.ChatID, "text": text, "disable_web_page_preview": true})
		req, err := http.NewRequestWithContext(c, http.MethodPost, t.APIBaseURL+"/bot"+t.BotToken+"/sendMessage", bytes.NewReader(body))
		if err != nil {
			return
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Log.Warn("telegram notification failed", "kind", kind, "room_id", roomID, "error_type", "request_error")
			return
		}
		defer resp.Body.Close()
		if resp.StatusCode >= 300 {
			t.Log.Warn("telegram notification failed", "kind", kind, "room_id", roomID, "status", resp.StatusCode)
			return
		}
		t.Log.Info("telegram notification sent", "kind", kind, "room_id", roomID)
	}()
}
