package room

import (
	"context"
	"strings"

	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
)

// AI relay *state* is owned here (authorization, room state, events). Starting or
// stopping the BRSE AI participant is done by the Python interpreter, which reacts
// to room.brse_updated / room.relay_mode_updated / participant.* on Redis.

func (s *Service) requireAIPermission(ctx context.Context, roomID, participantID string) error {
	if _, _, err := s.RequirePermission(ctx, roomID, participantID, PermManageAI); err != nil {
		return &BrseForbiddenError{Code: "permission_denied", Message: PermissionDeniedMessage}
	}
	return nil
}

// SetBrseEnabled mirrors set_brse_enabled (+ _set_brse_enabled_locked).
func (s *Service) SetBrseEnabled(ctx context.Context, roomID string, enabled bool, actorID, sessionID, reason string) (*models.RoomResponse, error) {
	unlock := s.roomLock(ctx, roomID)
	defer unlock()
	snapshot, err := s.Store.GetRoomSnapshot(ctx, roomID, false)
	if err != nil {
		return nil, err
	}
	if snapshot == nil {
		return nil, ErrRoomNotFound
	}
	if actorID == "" {
		return nil, &BrseForbiddenError{Code: "brse_toggle_forbidden", Message: "authenticated participant is required to change BRSE mode"}
	}
	actor, err := s.Store.GetParticipant(ctx, roomID, actorID)
	if err != nil {
		return nil, err
	}
	if actor == nil || actor.Status == "disconnected" || actor.IsVirtual {
		return nil, &BrseForbiddenError{Code: "brse_toggle_forbidden", Message: "active human participant is required to change BRSE mode"}
	}
	if sessionID != "" && actor.SessionID != sessionID {
		return nil, &BrseForbiddenError{Code: "session_mismatch", Message: "session is no longer valid"}
	}
	if err := s.requireAIPermission(ctx, roomID, actorID); err != nil {
		return nil, err
	}
	room := snapshot.State
	if room.BrseEnabled == enabled {
		if !enabled {
			_, _ = s.Store.UpdateRoom(ctx, roomID, map[string]any{"virtual_participants": []any{}})
			_ = s.Store.ClearTranscripts(ctx, roomID)
		}
		fresh, err := s.Store.GetRoomState(ctx, roomID)
		if err != nil {
			return nil, err
		}
		if fresh == nil {
			return nil, ErrRoomNotFound
		}
		resp := fresh.Response()
		return &resp, nil
	}
	now := platform.NowStr()
	langs := roomLanguages(room)
	brseMode := models.NormalizeBrseMode(room.BrseMode)
	requested := models.NormalizeBrseOutputMode(room.BrseOutputMode)
	effective, downgrade := models.ResolveEffectiveOutputMode(langs, requested)
	if downgrade != nil {
		s.logger(ctx).Info("room output mode downgraded on BRSE toggle", "room_id", roomID, "reason", *downgrade)
	}
	virtual := []models.ParticipantSnapshot{}
	if enabled {
		joined := now
		virtual = append(virtual, models.BuildBrseVirtualParticipant(roomID, &joined, langs, brseMode, requested))
	}
	updated, err := s.Store.UpdateRoom(ctx, roomID, map[string]any{
		"brse_enabled":         enabled,
		"brse_mode":            brseMode,
		"brse_output_mode":     effective,
		"meeting_mode":         models.MeetingModeForBrseMode(brseMode),
		"interpreter_mode":     models.InterpreterModeBrseParticipant,
		"room_languages":       langs,
		"meeting_languages":    langs,
		"audio_routing":        models.BuildAudioRouting(langs, brseMode, requested),
		"virtual_participants": virtual,
	})
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, ErrRoomNotFound
	}
	if !enabled {
		_ = s.Store.ClearTranscripts(ctx, roomID)
	}
	action := "ai_relay_disabled"
	if enabled {
		action = "ai_relay_enabled"
	}
	s.audit(ctx, action, roomID, "actor", actorID)
	s.History.Schedule(ctx, "room_mode_updated", roomID, func(c context.Context) error {
		return s.History.PersistRoomModeUpdated(c, updated, now)
	})
	_ = s.Publish(ctx, "room.brse_updated", roomID, map[string]any{
		"room_id": roomID, "brse_enabled": enabled, "brse_mode": brseMode, "brse_output_mode": effective,
		"timestamp": now, "changed_by": actorID, "reason": reason,
	})
	if enabled {
		count := models.ActiveHumanCount(snapshot.Participants)
		for _, p := range updated.VirtualParticipants {
			participant := p
			s.History.Schedule(ctx, "virtual_participant_joined", roomID, func(c context.Context) error {
				return s.History.PersistParticipantJoin(c, updated, participantFromSnapshotForHistory(participant), count, nil, "")
			})
			_ = s.Publish(ctx, "participant.joined", roomID, participant)
		}
	} else {
		_ = s.Publish(ctx, "participant.left", roomID, map[string]any{
			"participant_id": models.BrseParticipantID, "left_at": now, "reason": "brse_disabled",
		})
	}
	resp := updated.Response()
	return &resp, nil
}

func participantFromSnapshotForHistory(p models.ParticipantSnapshot) history.JoinParticipant {
	return history.JoinParticipant{
		ParticipantID: p.ParticipantID, DisplayName: p.DisplayName, Language: p.Language, Kind: p.Kind,
		IsVirtual: p.IsVirtual, LiveKitIdentity: p.LiveKitIdentity, Metadata: p.Metadata, JoinedAt: p.JoinedAt,
		LastSeenAt: p.LastSeenAt, Status: p.Status,
	}
}

// SetRelayMode mirrors set_relay_mode (Voice + Text <-> Text Only in a live room).
func (s *Service) SetRelayMode(ctx context.Context, roomID, mode, actorID, sessionID, reason string) (*models.RoomResponse, error) {
	unlock := s.roomLock(ctx, roomID)
	defer unlock()
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
	if actorID == "" {
		return nil, &BrseForbiddenError{Code: "relay_mode_forbidden", Message: "authenticated participant is required to change the AI relay mode"}
	}
	actor, err := s.Store.GetParticipant(ctx, roomID, actorID)
	if err != nil {
		return nil, err
	}
	if actor == nil || actor.Status == "disconnected" || actor.IsVirtual {
		return nil, &BrseForbiddenError{Code: "relay_mode_forbidden", Message: "active human participant is required to change the AI relay mode"}
	}
	if sessionID != "" && actor.SessionID != sessionID {
		return nil, &BrseForbiddenError{Code: "session_mismatch", Message: "session is no longer valid"}
	}
	if err := s.requireAIPermission(ctx, roomID, actorID); err != nil {
		return nil, err
	}
	room := snapshot.State
	langs := roomLanguages(room)
	brseMode := models.NormalizeBrseMode(room.BrseMode)
	if brseMode == models.BrseModeSilentSummary {
		return nil, &RelayModeNotSupportedError{Message: "Summary capture rooms do not publish relay output."}
	}
	allowed := models.SelectableOutputModes(langs)
	if !contains(allowed, mode) {
		msg := "This relay mode is not available for this room."
		if mode == models.BrseOutputVoiceText {
			msg = "AI voice is only available in rooms with exactly two languages."
		}
		return nil, &RelayModeNotSupportedError{Message: msg}
	}
	previous := models.NormalizeBrseOutputMode(room.BrseOutputMode)
	if previous == mode {
		resp := room.Response()
		return &resp, nil
	}
	now := platform.NowStr()
	routing := models.BuildAudioRouting(langs, brseMode, mode)
	patch := map[string]any{"brse_output_mode": mode, "audio_routing": routing}
	if room.BrseEnabled {
		joined := now
		patch["virtual_participants"] = []models.ParticipantSnapshot{models.BuildBrseVirtualParticipant(roomID, &joined, langs, brseMode, mode)}
	}
	updated, err := s.Store.UpdateRoom(ctx, roomID, patch)
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, ErrRoomNotFound
	}
	s.logger(ctx).Info("relay mode changed", "event", "relay_mode_changed", "room_id", roomID, "from", previous, "to", mode, "changed_by", actorID, "reason", reason)
	s.audit(ctx, "ai_mode_changed", roomID, "actor", actorID, "mode", mode)
	s.History.Schedule(ctx, "room_mode_updated", roomID, func(c context.Context) error {
		return s.History.PersistRoomModeUpdated(c, updated, now)
	})
	_ = s.Publish(ctx, "room.relay_mode_updated", roomID, map[string]any{
		"room_id": roomID, "brse_enabled": updated.BrseEnabled, "brse_mode": brseMode, "brse_output_mode": mode,
		"previous_output_mode": previous, "audio_routing": routing, "changed_at": now, "changed_by": actorID, "reason": reason,
	})
	resp := updated.Response()
	return &resp, nil
}

// ── Chat ──────────────────────────────────────────────────────────────────

const MaxChatMessageLength = 2000

// SendChatMessage mirrors send_chat_message. Translation (AI) is delegated to Python;
// if it fails the message is sent untranslated, exactly as before.
func (s *Service) SendChatMessage(ctx context.Context, roomID, participantID, sessionID string, text any, clientEventID string, translationMode string) (*models.ChatMessage, error) {
	raw, ok := text.(string)
	if !ok {
		return nil, &ChatError{Code: "invalid_chat_message", Message: "text must be a string"}
	}
	normalized := strings.TrimSpace(raw)
	if normalized == "" {
		return nil, &ChatError{Code: "empty_chat_message", Message: "message text must not be empty"}
	}
	if len([]rune(normalized)) > MaxChatMessageLength {
		return nil, &ChatError{Code: "chat_message_too_long", Message: "message text must be at most 2000 characters"}
	}
	snapshot, err := s.Store.GetRoomSnapshot(ctx, roomID, false)
	if err != nil {
		return nil, err
	}
	if snapshot == nil {
		return nil, ErrRoomNotFound
	}
	if clientEventID != "" {
		for _, m := range snapshot.RecentMessages {
			if m.ClientEventID != nil && *m.ClientEventID == clientEventID {
				existing := m
				return &existing, nil
			}
		}
	}
	p, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil {
		return nil, err
	}
	if p == nil {
		return nil, ErrParticipantNotFound
	}
	if sessionID != "" && p.SessionID != sessionID {
		return nil, &ChatError{Code: "session_mismatch", Message: "session is no longer valid"}
	}
	if p.Status == "disconnected" {
		return nil, ErrParticipantNotFound
	}
	if p.IsVirtual {
		return nil, &ChatError{Code: "chat_not_allowed", Message: "virtual participants cannot send chat"}
	}
	now := platform.NowStr()
	translations := []models.ChatTranslation{}
	if translationMode == "translate" && s.AI != nil {
		result, err := s.AI.TranslateChat(ctx, roomID, normalized, p.Language, roomLanguages(snapshot.State))
		if err != nil {
			s.logger(ctx).Warn("chat translation unavailable; message sent untranslated", "room_id", roomID, "error", err.Error())
		}
		for _, t := range result {
			if t.Text != "" {
				translations = append(translations, models.ChatTranslation{Language: t.Language, Text: t.Text})
			}
		}
	}
	var clientID *string
	if clientEventID != "" {
		clientID = &clientEventID
	}
	sender, senderName, senderLanguage := p.ParticipantID, p.DisplayName, p.Language
	message := &models.ChatMessage{
		MessageID:         platform.GenerateID("msg"),
		RoomID:            roomID,
		ParticipantID:     p.ParticipantID,
		DisplayName:       p.DisplayName,
		Language:          p.Language,
		Text:              normalized,
		CreatedAt:         now,
		ClientEventID:     clientID,
		SenderID:          &sender,
		SenderDisplayName: &senderName,
		SenderLanguage:    &senderLanguage,
		SentAt:            &now,
		TranslationMode:   translationMode,
		Translations:      translations,
	}
	if err := s.Store.AppendChat(ctx, roomID, message); err != nil {
		return nil, err
	}
	_ = s.Store.UpdateParticipant(ctx, roomID, participantID, map[string]any{"last_seen_at": now})
	s.History.Schedule(ctx, "chat_message", roomID, func(c context.Context) error {
		return s.History.PersistChat(c, message, true)
	})
	_ = s.Publish(ctx, "chat.message", roomID, message)
	return message, nil
}
