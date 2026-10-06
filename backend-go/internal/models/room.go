package models

import (
	"encoding/json"
)

const (
	RoleHost        = "host"
	RoleCoHost      = "co_host"
	RoleParticipant = "participant"
)

type AudioRouting struct {
	Model                     string              `json:"model"`
	CrossLanguageRemoteAudio  string              `json:"cross_language_remote_audio"`
	CanonicalRemoteAudio      string              `json:"canonical_remote_audio"`
	SameLanguagePolicy        string              `json:"same_language_policy"`
	AIRelayAudio              string              `json:"ai_relay_audio"`
	InterpreterMode           string              `json:"interpreter_mode"`
	BridgeStrategy            string              `json:"bridge_strategy"`
	RelayLanguageMap          map[string]string   `json:"relay_language_map"`
	RelayLanguageTargets      map[string][]string `json:"relay_language_targets"`
	VirtualParticipantID      string              `json:"virtual_participant_id"`
	BrseMode                  string              `json:"brse_mode"`
	BrseOutputMode            string              `json:"brse_output_mode"`
	RequestedBrseOutputMode   string              `json:"requested_brse_output_mode"`
	OutputModeDowngradeReason *string             `json:"output_mode_downgrade_reason"`
	AIAudioOutputEnabled      bool                `json:"ai_audio_output_enabled"`
	RelayTextOutputEnabled    bool                `json:"relay_text_output_enabled"`
	AIAudioSuppressedReason   *string             `json:"ai_audio_suppressed_reason"`
	SourceTranscriptCapture   bool                `json:"source_transcript_capture"`
	RelayTranscriptPolicy     string              `json:"relay_transcript_policy"`
	RouteStrategy             string              `json:"route_strategy"`
	RoomLanguageCount         int                 `json:"room_language_count"`
}

type ScreenShareTrackInfo struct {
	Active    bool    `json:"active"`
	Source    string  `json:"source"`
	TrackSID  *string `json:"track_sid"`
	TrackName *string `json:"track_name"`
	StartedAt string  `json:"started_at"`
}

// ParticipantState is the Redis record of one realtime session (room:{id}:participants).
type ParticipantState struct {
	ParticipantID   string                `json:"participant_id"`
	SessionID       string                `json:"session_id"`
	DisplayName     string                `json:"display_name"`
	Language        string                `json:"language"`
	Status          string                `json:"status"`
	JoinedAt        string                `json:"joined_at"`
	LastSeenAt      *string               `json:"last_seen_at"`
	LeftAt          *string               `json:"left_at"`
	WSConnected     bool                  `json:"ws_connected"`
	MediaConnected  bool                  `json:"media_connected"`
	Kind            string                `json:"kind"`
	IsVirtual       bool                  `json:"is_virtual"`
	LiveKitIdentity *string               `json:"livekit_identity"`
	Metadata        map[string]any        `json:"metadata"`
	IsScreenSharing bool                  `json:"is_screen_sharing"`
	ScreenShare     *ScreenShareTrackInfo `json:"screen_share"`
	Role            string                `json:"role"`
	MutedByHost     bool                  `json:"muted_by_host"`
}

func (p *ParticipantState) applyDefaults() {
	if p.Kind == "" {
		p.Kind = KindHuman
	}
	if p.Metadata == nil {
		p.Metadata = map[string]any{}
	}
	if p.Role == "" {
		p.Role = RoleParticipant
	}
}

func DecodeParticipant(raw []byte) (*ParticipantState, error) {
	var p ParticipantState
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, err
	}
	p.applyDefaults()
	return &p, nil
}

func (p ParticipantState) Snapshot() ParticipantSnapshot {
	joined := p.JoinedAt
	return ParticipantSnapshot{
		ParticipantID:   p.ParticipantID,
		DisplayName:     p.DisplayName,
		Language:        p.Language,
		Status:          p.Status,
		JoinedAt:        &joined,
		LastSeenAt:      p.LastSeenAt,
		WSConnected:     p.WSConnected,
		Kind:            p.Kind,
		IsVirtual:       p.IsVirtual,
		LiveKitIdentity: p.LiveKitIdentity,
		Metadata:        p.Metadata,
		IsScreenSharing: p.IsScreenSharing,
		ScreenShare:     p.ScreenShare,
		Role:            p.Role,
		MutedByHost:     p.MutedByHost,
	}
}

// ParticipantSnapshot is what clients see (and RoomState.virtual_participants).
type ParticipantSnapshot struct {
	ParticipantID   string                `json:"participant_id"`
	DisplayName     string                `json:"display_name"`
	Language        string                `json:"language"`
	Status          string                `json:"status"`
	JoinedAt        *string               `json:"joined_at"`
	LastSeenAt      *string               `json:"last_seen_at"`
	WSConnected     bool                  `json:"ws_connected"`
	Kind            string                `json:"kind"`
	IsVirtual       bool                  `json:"is_virtual"`
	LiveKitIdentity *string               `json:"livekit_identity"`
	Metadata        map[string]any        `json:"metadata"`
	IsScreenSharing bool                  `json:"is_screen_sharing"`
	ScreenShare     *ScreenShareTrackInfo `json:"screen_share"`
	Role            string                `json:"role"`
	MutedByHost     bool                  `json:"muted_by_host"`
}

func (p *ParticipantSnapshot) applyDefaults() {
	if p.Kind == "" {
		p.Kind = KindHuman
	}
	if p.Metadata == nil {
		p.Metadata = map[string]any{}
	}
	if p.Role == "" {
		p.Role = RoleParticipant
	}
}

// RoomState is room:{id}:meta.
type RoomState struct {
	RoomID              string                `json:"room_id"`
	State               string                `json:"state"`
	CreatedAt           string                `json:"created_at"`
	ActivatedAt         *string               `json:"activated_at"`
	EmptiedAt           *string               `json:"emptied_at"`
	ExpiresAt           string                `json:"expires_at"`
	BrseEnabled         bool                  `json:"brse_enabled"`
	BrseMode            string                `json:"brse_mode"`
	BrseOutputMode      string                `json:"brse_output_mode"`
	ParticipantLimit    *int                  `json:"participant_limit"`
	SupportedLanguages  []string              `json:"supported_languages"`
	RoomLanguages       []string              `json:"room_languages"`
	MeetingLanguages    []string              `json:"meeting_languages"`
	MeetingMode         string                `json:"meeting_mode"`
	InterpreterMode     string                `json:"interpreter_mode"`
	AudioRouting        AudioRouting          `json:"audio_routing"`
	VirtualParticipants []ParticipantSnapshot `json:"virtual_participants"`
	PasswordRequired    bool                  `json:"password_required"`
	Title               *string               `json:"title"`
	Locked              bool                  `json:"locked"`
	RolesEnabled        bool                  `json:"roles_enabled"`
}

// DecodeRoomState parses room meta and applies RoomState._normalize_language_aliases.
func DecodeRoomState(raw []byte) (*RoomState, error) {
	var generic map[string]any
	if err := json.Unmarshal(raw, &generic); err != nil {
		return nil, err
	}
	return RoomStateFromMap(generic)
}

// RoomStateFromMap normalizes a raw dict exactly like the pydantic "before" validator.
func RoomStateFromMap(data map[string]any) (*RoomState, error) {
	normalized := make(map[string]any, len(data))
	for k, v := range data {
		normalized[k] = v
	}
	var legacy []string
	if s, ok := normalized["language_a"].(string); ok {
		legacy = append(legacy, s)
	}
	if s, ok := normalized["language_b"].(string); ok {
		legacy = append(legacy, s)
	}
	if isEmpty(normalized["room_languages"]) {
		switch {
		case !isEmpty(normalized["meeting_languages"]):
			normalized["room_languages"] = normalized["meeting_languages"]
		case len(legacy) > 0:
			normalized["room_languages"] = toAny(legacy)
		default:
			normalized["room_languages"] = toAny(DefaultRoomLanguages)
		}
	}
	roomLanguages := NormalizeRoomLanguagesForRuntime(stringList(normalized["room_languages"]))
	normalized["room_languages"] = roomLanguages
	normalized["meeting_languages"] = roomLanguages
	requested := DefaultBrseOutputMode
	if s, ok := normalized["brse_output_mode"].(string); ok {
		requested = s
	} else if v, present := normalized["brse_output_mode"]; present && v != nil {
		requested = ""
	}
	effective, _ := ResolveEffectiveOutputMode(roomLanguages, requested)
	normalized["brse_output_mode"] = effective
	brseMode := DefaultBrseMode
	if s, ok := normalized["brse_mode"].(string); ok {
		brseMode = s
	}
	routing, ok := normalized["audio_routing"].(map[string]any)
	rebuild := !ok || routing == nil || routing["brse_output_mode"] != effective || !sameCount(routing["room_language_count"], len(roomLanguages))
	if rebuild {
		normalized["audio_routing"] = BuildAudioRouting(roomLanguages, brseMode, requested)
	}
	encoded, err := json.Marshal(normalized)
	if err != nil {
		return nil, err
	}
	room := RoomState{}
	if err := json.Unmarshal(encoded, &room); err != nil {
		return nil, err
	}
	room.applyDefaults(normalized)
	return &room, nil
}

func (r *RoomState) applyDefaults(raw map[string]any) {
	if _, ok := raw["brse_enabled"]; !ok {
		r.BrseEnabled = DefaultBrseEnabled
	}
	if r.BrseMode == "" {
		r.BrseMode = DefaultBrseMode
	}
	if r.BrseOutputMode == "" {
		r.BrseOutputMode = DefaultBrseOutputMode
	}
	if r.SupportedLanguages == nil {
		r.SupportedLanguages = append([]string{}, SupportedLanguages...)
	}
	if r.MeetingMode == "" {
		r.MeetingMode = MeetingModeBrseRelay
	}
	if r.InterpreterMode == "" {
		r.InterpreterMode = InterpreterModeBrseParticipant
	}
	if r.VirtualParticipants == nil {
		r.VirtualParticipants = []ParticipantSnapshot{}
	}
	for i := range r.VirtualParticipants {
		r.VirtualParticipants[i].applyDefaults()
	}
	if r.AudioRouting.RelayLanguageMap == nil {
		r.AudioRouting.RelayLanguageMap = map[string]string{}
	}
	if r.AudioRouting.RelayLanguageTargets == nil {
		r.AudioRouting.RelayLanguageTargets = map[string][]string{}
	}
}

func isEmpty(v any) bool {
	switch t := v.(type) {
	case nil:
		return true
	case []any:
		return len(t) == 0
	case []string:
		return len(t) == 0
	case string:
		return t == ""
	}
	return false
}

func stringList(v any) []string {
	switch t := v.(type) {
	case []string:
		return t
	case []any:
		out := make([]string, 0, len(t))
		for _, item := range t {
			if s, ok := item.(string); ok {
				out = append(out, s)
			}
		}
		return out
	}
	return nil
}

func toAny(list []string) []any {
	out := make([]any, len(list))
	for i, s := range list {
		out[i] = s
	}
	return out
}

func sameCount(v any, n int) bool {
	switch t := v.(type) {
	case float64:
		return int(t) == n
	case int:
		return t == n
	case json.Number:
		i, err := t.Int64()
		return err == nil && int(i) == n
	}
	return false
}

// RoomResponse is CreateRoomResponseRoom.
type RoomResponse struct {
	RoomID             string       `json:"room_id"`
	State              string       `json:"state"`
	CreatedAt          string       `json:"created_at"`
	ExpiresAt          string       `json:"expires_at"`
	BrseEnabled        bool         `json:"brse_enabled"`
	BrseMode           string       `json:"brse_mode"`
	BrseOutputMode     string       `json:"brse_output_mode"`
	ParticipantLimit   *int         `json:"participant_limit"`
	SupportedLanguages []string     `json:"supported_languages"`
	RoomLanguages      []string     `json:"room_languages"`
	MeetingLanguages   []string     `json:"meeting_languages"`
	MeetingMode        string       `json:"meeting_mode"`
	InterpreterMode    string       `json:"interpreter_mode"`
	AudioRouting       AudioRouting `json:"audio_routing"`
	PasswordRequired   bool         `json:"password_required"`
	Title              *string      `json:"title"`
	Locked             bool         `json:"locked"`
}

func (r RoomState) Response() RoomResponse {
	langs := r.RoomLanguages
	if len(langs) == 0 {
		langs = r.MeetingLanguages
	}
	if len(langs) == 0 {
		langs = append([]string{}, DefaultRoomLanguages...)
	}
	meeting := r.MeetingLanguages
	if len(meeting) == 0 {
		meeting = langs
	}
	return RoomResponse{
		RoomID:             r.RoomID,
		State:              r.State,
		CreatedAt:          r.CreatedAt,
		ExpiresAt:          r.ExpiresAt,
		BrseEnabled:        r.BrseEnabled,
		BrseMode:           r.BrseMode,
		BrseOutputMode:     r.BrseOutputMode,
		ParticipantLimit:   r.ParticipantLimit,
		SupportedLanguages: r.SupportedLanguages,
		RoomLanguages:      langs,
		MeetingLanguages:   meeting,
		MeetingMode:        r.MeetingMode,
		InterpreterMode:    r.InterpreterMode,
		AudioRouting:       r.AudioRouting,
		PasswordRequired:   r.PasswordRequired,
		Title:              r.Title,
		Locked:             r.Locked,
	}
}

// SnapshotRoom is RoomSnapshotResponseRoom.
type SnapshotRoom struct {
	RoomResponse
	ParticipantCount   int            `json:"participant_count"`
	Recording          map[string]any `json:"recording"`
	RecordingAvailable bool           `json:"recording_available"`
	HostParticipantID  *string        `json:"host_participant_id"`
}

type ChatTranslation struct {
	Language string `json:"language"`
	Text     string `json:"text"`
}

type ChatMessage struct {
	MessageID         string            `json:"message_id"`
	RoomID            string            `json:"room_id"`
	ParticipantID     string            `json:"participant_id"`
	DisplayName       string            `json:"display_name"`
	Language          string            `json:"language"`
	Text              string            `json:"text"`
	CreatedAt         string            `json:"created_at"`
	ClientEventID     *string           `json:"client_event_id"`
	SenderID          *string           `json:"sender_id"`
	SenderDisplayName *string           `json:"sender_display_name"`
	SenderLanguage    *string           `json:"sender_language"`
	SentAt            *string           `json:"sent_at"`
	TranslationMode   string            `json:"translation_mode"`
	Translations      []ChatTranslation `json:"translations"`
}

func (m *ChatMessage) applyDefaults() {
	if m.TranslationMode == "" {
		m.TranslationMode = "original_only"
	}
	if m.Translations == nil {
		m.Translations = []ChatTranslation{}
	}
}

func DecodeChat(raw []byte) (*ChatMessage, error) {
	var m ChatMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, err
	}
	m.applyDefaults()
	return &m, nil
}

// Transcript is a TranscriptEvent as written by the Python event consumer. It is
// passed through untouched (fields with defaults are filled like pydantic would).
type Transcript map[string]any

var transcriptDefaults = map[string]any{
	"utterance_id": nil, "kind": "relay", "speaker_language": "auto", "text": "",
	"is_final": true, "fallback_used": false, "listener_id": nil, "target_lang": nil,
	"translated_text": nil, "brse_text": nil, "audio_track_name": nil, "audio_output": nil,
	"relay_mode": nil, "relay_style": nil, "speaker": nil, "original_speaker": nil,
	"listener": nil, "brse_participant": nil, "relay_target": nil,
}

func DecodeTranscript(raw []byte) (Transcript, error) {
	var t map[string]any
	if err := json.Unmarshal(raw, &t); err != nil {
		return nil, err
	}
	for k, v := range transcriptDefaults {
		if _, ok := t[k]; !ok {
			t[k] = v
		}
	}
	return Transcript(t), nil
}

func (t Transcript) String(key string) string {
	s, _ := t[key].(string)
	return s
}

func (t Transcript) Bool(key string) bool {
	b, _ := t[key].(bool)
	return b
}
