package room

import (
	"context"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"

	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/notify"
	"meetq/backend-go/internal/platform"
	"meetq/backend-go/internal/store"
)

type CreateRoomInput struct {
	Languages       []string // nil = defaults (Python: None)
	BrseEnabled     bool
	BrseMode        string
	BrseOutputMode  string
	Password        *string
	Title           *string
	CreatedByUserID string
}

type CreateRoomResponse struct {
	Room models.RoomResponse `json:"room"`
	Join struct {
		APIPath  string `json:"api_path"`
		ShareURL string `json:"share_url"`
	} `json:"join"`
}

// normalizeRoomLanguages mirrors RoomService._normalize_room_languages.
func normalizeRoomLanguages(langs []string, provided bool) ([]string, error) {
	if !provided {
		return append([]string{}, models.DefaultRoomLanguages...), nil
	}
	if len(langs) == 0 {
		return nil, &InvalidMeetingLanguagesError{Message: "room_languages must contain at least 1 language", Details: map[string]any{"field": "room_languages", "min_items": 1}}
	}
	invalid := []any{}
	out := []string{}
	for _, raw := range langs {
		lang := strings.ToLower(strings.TrimSpace(raw))
		if !models.IsSupportedLanguage(lang) {
			invalid = append(invalid, raw)
			continue
		}
		if contains(out, lang) {
			continue
		}
		out = append(out, lang)
	}
	if len(invalid) > 0 {
		return nil, &InvalidMeetingLanguagesError{Message: "room_languages contains unsupported language", Details: map[string]any{
			"field": "room_languages", "unsupported": invalid, "supported": models.SupportedLanguages,
		}}
	}
	if len(out) == 0 {
		return nil, &InvalidMeetingLanguagesError{Message: "room_languages must contain at least 1 language", Details: map[string]any{"field": "room_languages", "min_items": 1}}
	}
	return out, nil
}

func contains(list []string, v string) bool {
	for _, item := range list {
		if item == v {
			return true
		}
	}
	return false
}

func (s *Service) CreateRoom(ctx context.Context, in CreateRoomInput, languagesProvided bool) (*CreateRoomResponse, error) {
	roomLanguages, err := normalizeRoomLanguages(in.Languages, languagesProvided)
	if err != nil {
		return nil, err
	}
	roomID := platform.GenerateID("rm")
	now := platform.NowStr()
	expiresAt := s.expiresAt()
	brseMode := models.NormalizeBrseMode(in.BrseMode)
	requested := models.NormalizeBrseOutputMode(in.BrseOutputMode)
	effective, downgrade := models.ResolveEffectiveOutputMode(roomLanguages, requested)
	routing := models.BuildAudioRouting(roomLanguages, brseMode, requested)
	s.logger(ctx).Info("room language config resolved", "room_id", roomID, "room_languages", roomLanguages,
		"requested_output_mode", requested, "effective_output_mode", effective, "downgrade_reason", ptrStr(downgrade))
	virtual := []models.ParticipantSnapshot{}
	if in.BrseEnabled {
		joined := now
		virtual = append(virtual, models.BuildBrseVirtualParticipant(roomID, &joined, roomLanguages, brseMode, requested))
	}
	room := &models.RoomState{
		RoomID:              roomID,
		State:               "created",
		CreatedAt:           now,
		ExpiresAt:           expiresAt,
		BrseEnabled:         in.BrseEnabled,
		BrseMode:            brseMode,
		BrseOutputMode:      effective,
		ParticipantLimit:    nil,
		SupportedLanguages:  append([]string{}, models.SupportedLanguages...),
		RoomLanguages:       roomLanguages,
		MeetingLanguages:    roomLanguages,
		MeetingMode:         models.MeetingModeForBrseMode(brseMode),
		InterpreterMode:     models.InterpreterModeBrseParticipant,
		AudioRouting:        routing,
		VirtualParticipants: virtual,
		PasswordRequired:    in.Password != nil,
		Title:               in.Title,
		RolesEnabled:        in.CreatedByUserID != "",
	}
	if in.Password != nil {
		// Store the hash before the room exists, so a protected room is never joinable without it.
		if err := s.Access.SetPassword(ctx, roomID, *in.Password); err != nil {
			return nil, err
		}
	}
	if in.CreatedByUserID != "" {
		// The signed-in creator is the room's host for its whole lifetime (by user ID).
		if err := s.Members.SetHost(ctx, roomID, in.CreatedByUserID, now); err != nil {
			return nil, err
		}
	}
	if err := s.Store.CreateRoom(ctx, room); err != nil {
		return nil, err
	}
	s.audit(ctx, "room_created", roomID, "host_user", in.CreatedByUserID, "password", in.Password != nil)
	_ = s.Publish(ctx, "room.created", roomID, room)
	for _, p := range room.VirtualParticipants {
		_ = s.Publish(ctx, "participant.joined", roomID, p)
	}
	shareURL := s.publicAppURL("/rooms/" + roomID)
	createdBy := in.CreatedByUserID
	s.History.Schedule(ctx, "room_created", roomID, func(c context.Context) error {
		return s.History.PersistRoomCreated(c, room, shareURL, createdBy)
	})
	s.scheduleExpiry(room)
	s.Notifier.RoomCreated(ctx, notify.RoomInfo{
		RoomID: roomID, MeetingLanguages: room.MeetingLanguages, BrseEnabled: room.BrseEnabled,
		CreatedAt: room.CreatedAt, ExpiresAt: room.ExpiresAt, ParticipantLimit: room.ParticipantLimit,
	}, shareURL)
	resp := &CreateRoomResponse{Room: room.Response()}
	resp.Join.APIPath = "/api/rooms/" + roomID + "/join"
	resp.Join.ShareURL = shareURL
	return resp, nil
}

func ptrStr(p *string) string {
	if p == nil {
		return "-"
	}
	return *p
}

// GetRoom mirrors RoomService.get_room plus the recording fields added by the route.
func (s *Service) GetRoom(ctx context.Context, roomID string, includePrivate bool) (*store.Snapshot, error) {
	snapshot, err := s.Store.GetRoomSnapshot(ctx, roomID, false)
	if err != nil {
		return nil, err
	}
	if snapshot == nil {
		return nil, ErrRoomNotFound
	}
	if snapshot.State.PasswordRequired && !includePrivate {
		// Lobby view of a protected room: settings only; names, transcripts and chat are for members.
		virtual := []models.ParticipantSnapshot{}
		for _, p := range snapshot.Participants {
			if p.IsVirtual {
				virtual = append(virtual, p)
			}
		}
		snapshot.Participants = virtual
		snapshot.RecentTranscripts = []models.Transcript{}
		snapshot.RecentMessages = []models.ChatMessage{}
	}
	if s.Recording != nil {
		current, err := s.Recording.Current(ctx, roomID)
		if err == nil {
			snapshot.Room.Recording = current
		}
		snapshot.Room.RecordingAvailable = s.Recording.Available()
	}
	return snapshot, nil
}

// IsPasswordProtected: live rooms from Redis, ended rooms from history.
func (s *Service) IsPasswordProtected(ctx context.Context, roomID string) (bool, error) {
	room, err := s.Store.GetRoomState(ctx, roomID)
	if err != nil {
		return false, err
	}
	if room != nil {
		return room.PasswordRequired, nil
	}
	if s.History.Enabled() {
		return s.History.RoomPasswordRequired(ctx, roomID)
	}
	return false, nil
}

type JoinInput struct {
	DisplayName string
	Language    string
	Client      map[string]any
	UserID      string
	Password    *string
	ClientIP    string
}

type JoinResponse struct {
	Room        models.RoomResponse `json:"room"`
	Participant struct {
		ParticipantID string `json:"participant_id"`
		SessionID     string `json:"session_id"`
		DisplayName   string `json:"display_name"`
		Language      string `json:"language"`
		Role          string `json:"role"`
	} `json:"participant"`
	RoomToken struct {
		Token     string `json:"token"`
		ExpiresAt string `json:"expires_at"`
	} `json:"room_token"`
	Websocket struct {
		URL string `json:"url"`
	} `json:"websocket"`
	LiveKit struct {
		URL                 string `json:"url"`
		RoomName            string `json:"room_name"`
		ParticipantIdentity string `json:"participant_identity"`
		ParticipantName     string `json:"participant_name"`
		Token               string `json:"token"`
	} `json:"livekit"`
	Snapshot SnapshotData `json:"snapshot"`
}

type SnapshotData struct {
	Participants      []models.ParticipantSnapshot `json:"participants"`
	RecentTranscripts []models.Transcript          `json:"recent_transcripts"`
	RecentMessages    []models.ChatMessage         `json:"recent_messages"`
}

// TranscriptVisible: source/relay lines for everyone, private translations for their listener.
func TranscriptVisible(t models.Transcript, participantID string) bool {
	kind := t.String("kind")
	if kind == "source" || kind == "relay" {
		return true
	}
	return t.String("listener_id") == participantID
}

func PersonalizedSnapshot(snapshot *store.Snapshot, participantID string) SnapshotData {
	transcripts := []models.Transcript{}
	for _, t := range snapshot.RecentTranscripts {
		if TranscriptVisible(t, participantID) {
			transcripts = append(transcripts, t)
		}
	}
	return SnapshotData{Participants: snapshot.Participants, RecentTranscripts: transcripts, RecentMessages: snapshot.RecentMessages}
}

func (s *Service) JoinRoom(ctx context.Context, roomID string, in JoinInput) (*JoinResponse, error) {
	snapshot, err := s.Store.GetRoomSnapshot(ctx, roomID, false)
	if err != nil {
		return nil, err
	}
	if snapshot == nil {
		return nil, ErrRoomNotFound
	}
	// Admission order: exists → not expired → not removed → not locked → password →
	// capacity / language. No token is issued before every check passed.
	if isExpired(snapshot.Room.ExpiresAt) {
		s.ScheduleRoomExpiredArchival(ctx, snapshot.State, snapshot.Room.ExpiresAt, models.ActiveHumanCount(snapshot.Participants), "join_rejected_expired")
		return nil, ErrRoomExpired
	}
	member, err := s.Members.Get(ctx, roomID, in.UserID)
	if err != nil {
		return nil, err
	}
	if member != nil && str(member["removed_at"]) != "" {
		s.audit(ctx, "join_rejected_removed", roomID, "user", in.UserID)
		return nil, ErrParticipantRemoved
	}
	if snapshot.State.Locked && !(member != nil && (str(member["joined_at"]) != "" || member["role"] == models.RoleHost || member["role"] == models.RoleCoHost)) {
		s.audit(ctx, "join_rejected_locked", roomID, "user", in.UserID)
		return nil, ErrRoomLocked
	}
	if snapshot.State.PasswordRequired {
		if err := s.Access.CheckJoin(ctx, roomID, in.Password, in.ClientIP, in.UserID); err != nil {
			if err == ErrInvalidPassword {
				s.logger(ctx).Info("room password rejected", "room_id", roomID)
			}
			return nil, err
		}
	}
	if limit := snapshot.State.ParticipantLimit; limit != nil && *limit > 0 && models.ActiveHumanCount(snapshot.Participants) >= *limit {
		return nil, ErrRoomFull
	}
	langs := roomLanguages(snapshot.State)
	if in.Language == "auto" || !contains(langs, in.Language) {
		return nil, invalidRoomLanguage(langs)
	}
	now := platform.NowStr()
	if snapshot.State.State == "created" || snapshot.State.State == "empty" {
		if err := s.Store.ActivateRoom(ctx, roomID, now); err != nil {
			return nil, err
		}
	}
	participantID := platform.GenerateID("pt")
	sessionID := platform.GenerateID("ses")
	role := models.RoleParticipant
	if in.UserID != "" {
		// Role from the user's membership: a reconnect gets the same role back.
		m, err := s.Members.EnsureMember(ctx, roomID, in.UserID, now)
		if err != nil {
			return nil, err
		}
		role = NormalizeRole(str(m["role"]))
		if err := s.Members.LinkParticipant(ctx, roomID, participantID, in.UserID); err != nil {
			return nil, err
		}
	}
	identity := participantID
	participant := &models.ParticipantState{
		ParticipantID:   participantID,
		SessionID:       sessionID,
		DisplayName:     in.DisplayName,
		Language:        in.Language,
		Status:          "joining",
		JoinedAt:        now,
		LastSeenAt:      &now,
		Kind:            models.KindHuman,
		LiveKitIdentity: &identity,
		Metadata:        map[string]any{},
		Role:            role,
	}
	if err := s.Store.AddParticipant(ctx, roomID, participant); err != nil {
		return nil, err
	}
	_ = s.Publish(ctx, "participant.joined", roomID, participant)
	ttl := time.Duration(s.Cfg.RoomTokenTTLSeconds) * time.Second
	roomToken, err := IssueRoomToken(roomID, participantID, sessionID, in.DisplayName, in.Language, s.Cfg.RoomJWTSecret, ttl)
	if err != nil {
		return nil, err
	}
	lkToken, err := s.LiveKit.JoinToken(roomID, participantID, in.DisplayName, in.Language, "human", participantID, ttl, true)
	if err != nil {
		return nil, err
	}
	fresh, err := s.Store.GetRoomSnapshot(ctx, roomID, false)
	if err != nil || fresh == nil {
		return nil, ErrRoomNotFound
	}
	count := models.ActiveHumanCount(fresh.Participants)
	freshState := fresh.State
	clientMeta := in.Client
	userID := in.UserID
	s.History.Schedule(ctx, "participant_joined", roomID, func(c context.Context) error {
		if err := s.History.PersistParticipantJoin(c, freshState, history.ParticipantFromState(participant), count, clientMetaValue(clientMeta), userID); err != nil {
			return err
		}
		return nil
	})
	if userID != "" {
		s.History.Schedule(ctx, "membership_joined", roomID, func(c context.Context) error {
			return s.History.PersistMembership(c, roomID, userID, history.MembershipFields{Role: role, DisplayName: in.DisplayName, Language: in.Language, JoinedAt: now})
		})
	}
	s.Notifier.ParticipantJoined(ctx, notify.RoomInfo{
		RoomID: roomID, MeetingLanguages: freshState.MeetingLanguages, BrseEnabled: freshState.BrseEnabled,
	}, notify.ParticipantInfo{ParticipantID: participantID, DisplayName: in.DisplayName, Language: in.Language, JoinedAt: now}, count)

	resp := &JoinResponse{Room: freshState.Response(), Snapshot: PersonalizedSnapshot(fresh, participantID)}
	resp.Participant.ParticipantID = participantID
	resp.Participant.SessionID = sessionID
	resp.Participant.DisplayName = in.DisplayName
	resp.Participant.Language = in.Language
	resp.Participant.Role = role
	resp.RoomToken.Token = roomToken
	resp.RoomToken.ExpiresAt = s.tokenExpiresAt()
	resp.Websocket.URL = s.publicGatewayWSURL("/ws/rooms/" + roomID + "?token=" + roomToken)
	resp.LiveKit.URL = s.Cfg.LiveKitWSURLPublic
	resp.LiveKit.RoomName = roomID
	resp.LiveKit.ParticipantIdentity = participantID
	resp.LiveKit.ParticipantName = in.DisplayName
	resp.LiveKit.Token = lkToken
	return resp, nil
}

func clientMetaValue(m map[string]any) any {
	if m == nil {
		return nil
	}
	return bson.M(m)
}
