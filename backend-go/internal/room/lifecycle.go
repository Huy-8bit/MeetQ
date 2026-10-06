package room

import (
	"context"
	"time"

	"meetq/backend-go/internal/ai"
	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
)

// ── Leave / cleanup ───────────────────────────────────────────────────────

func (s *Service) LeaveRoom(ctx context.Context, roomID, participantID, sessionID string) {
	s.CleanupParticipant(ctx, roomID, participantID, sessionID, "rest_leave")
}

// CleanupParticipant mirrors RoomService.cleanup_participant.
func (s *Service) CleanupParticipant(ctx context.Context, roomID, participantID, sessionID, reason string) bool {
	participant, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil || participant == nil {
		return false
	}
	if sessionID != "" && participant.SessionID != sessionID {
		return false
	}
	if participant.Status == "disconnected" {
		_ = s.Store.RemoveParticipant(ctx, roomID, participantID)
		return true
	}
	if participant.IsScreenSharing {
		_, _ = s.StopScreenShare(ctx, roomID, participantID, participant.SessionID, reason+"_participant_cleanup")
	}
	now := platform.NowStr()
	_ = s.Store.RemoveParticipant(ctx, roomID, participantID)
	userID, _ := s.Members.UserForParticipant(ctx, roomID, participantID)
	_ = s.Publish(ctx, "participant.left", roomID, map[string]any{
		"participant_id": participantID,
		"session_id":     participant.SessionID,
		"left_at":        now,
		"reason":         reason,
	})
	fresh, _ := s.Store.GetRoomSnapshot(ctx, roomID, false)
	count := 0
	if fresh != nil {
		count = models.ActiveHumanCount(fresh.Participants)
	}
	terminal := ""
	if fresh != nil && count == 0 {
		terminal = "empty"
		_ = s.Store.MarkRoomEmpty(ctx, roomID, now)
		s.notifyRoomEnded(ctx, roomID, "last_participant_left")
	}
	stillHere := false
	if userID != "" && fresh != nil {
		others, _ := s.Members.ParticipantsForUser(ctx, roomID, userID)
		for _, other := range others {
			if other == participantID {
				continue
			}
			for _, p := range fresh.Participants {
				if p.ParticipantID == other {
					stillHere = true
				}
			}
		}
	}
	language := participant.Language
	s.History.Schedule(ctx, "participant_left", roomID, func(c context.Context) error {
		if err := s.History.PersistParticipantLeft(c, roomID, participant, now, reason, count, terminal); err != nil {
			return err
		}
		if userID != "" && !stillHere {
			if err := s.History.PersistMembershipLeft(c, roomID, userID, now); err != nil {
				return err
			}
		}
		if terminal != "" {
			s.requestFinalSummary(c, roomID, terminal+":"+reason, &now, &language)
		}
		return nil
	})
	return true
}

// notifyRoomEnded: an active recording stops when the meeting ends (Python: room_end_listeners).
func (s *Service) notifyRoomEnded(ctx context.Context, roomID, reason string) {
	if s.Recording == nil {
		return
	}
	detached := context.WithoutCancel(ctx)
	go func() {
		c, cancel := context.WithTimeout(detached, 30*time.Second)
		defer cancel()
		s.Recording.StopForRoomEnd(c, roomID, reason)
	}()
}

// requestFinalSummary asks the Python AI service for the end-of-meeting summary.
// A failure is logged; the meeting end itself is already persisted.
func (s *Service) requestFinalSummary(ctx context.Context, roomID, trigger string, endedAt, requesterLanguage *string) {
	if s.AI == nil || !s.AI.Configured() {
		s.logger(ctx).Warn("final summary skipped: python ai service not configured", "room_id", roomID)
		return
	}
	err := s.AI.RequestFinalSummary(ctx, roomID, ai.FinalSummaryRequest{TriggerReason: trigger, EndedAt: endedAt, RequesterLanguage: requesterLanguage})
	if err != nil {
		s.logger(ctx).Error("final summary request failed", "room_id", roomID, "trigger", trigger, "error", err.Error())
	}
}

// ── Expiry ────────────────────────────────────────────────────────────────

// scheduleExpiry mirrors _schedule_room_expiry_summary (in-memory timer per room, as in Python).
func (s *Service) scheduleExpiry(room *models.RoomState) {
	if !s.Cfg.ExpirySchedulerEnabled || !s.History.Enabled() {
		return
	}
	expires := platform.ParseTime(room.ExpiresAt)
	if expires == nil {
		return
	}
	delay := expires.Sub(platform.NowUTC())
	if delay < 0 {
		delay = 0
	}
	roomID, expiresAt := room.RoomID, room.ExpiresAt
	s.expiryMu.Lock()
	if s.expiryTimer == nil {
		s.expiryTimer = map[string]*time.Timer{}
	}
	if old := s.expiryTimer[roomID]; old != nil {
		old.Stop()
	}
	s.expiryTimer[roomID] = time.AfterFunc(delay, func() {
		s.expiryMu.Lock()
		delete(s.expiryTimer, roomID)
		s.expiryMu.Unlock()
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		snapshot, _ := s.Store.GetRoomSnapshot(ctx, roomID, false)
		var state *models.RoomState
		count := 0
		if snapshot != nil {
			state = snapshot.State
			count = models.ActiveHumanCount(snapshot.Participants)
		}
		s.persistRoomExpiredAndSummary(ctx, state, roomID, expiresAt, count, "scheduled_expiry")
	})
	s.expiryMu.Unlock()
}

// StopExpiryTimers is called on shutdown.
func (s *Service) StopExpiryTimers() {
	s.expiryMu.Lock()
	defer s.expiryMu.Unlock()
	for id, t := range s.expiryTimer {
		t.Stop()
		delete(s.expiryTimer, id)
	}
}

// ScheduleRoomExpiredArchival mirrors schedule_room_expired_archival.
func (s *Service) ScheduleRoomExpiredArchival(ctx context.Context, room *models.RoomState, expiredAt string, count int, reason string) {
	if room == nil || !s.History.Enabled() {
		return
	}
	s.History.Schedule(ctx, "room_expired", room.RoomID, func(c context.Context) error {
		s.persistRoomExpiredAndSummary(c, room, room.RoomID, expiredAt, count, reason)
		return nil
	})
}

func (s *Service) persistRoomExpiredAndSummary(ctx context.Context, room *models.RoomState, roomID, expiredAt string, count int, reason string) {
	s.notifyRoomEnded(ctx, roomID, "room_expired")
	if err := s.History.PersistRoomExpired(ctx, room, roomID, expiredAt, count, reason); err != nil {
		s.logger(ctx).Error("persist room expired failed", "room_id", roomID, "error", err.Error())
	}
	var endedAt *string
	if expiredAt != "" {
		endedAt = &expiredAt
	}
	s.requestFinalSummary(ctx, roomID, reason, endedAt, nil)
}

// ── Screen share ──────────────────────────────────────────────────────────

// StartScreenShare mirrors start_screen_share; false = session mismatch / disconnected.
func (s *Service) StartScreenShare(ctx context.Context, roomID, participantID, sessionID string, trackSID, trackName *string) (bool, error) {
	p, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil {
		return false, err
	}
	if p == nil {
		return false, ErrParticipantNotFound
	}
	if sessionID != "" && p.SessionID != sessionID {
		return false, nil
	}
	if p.Status == "disconnected" {
		return false, nil
	}
	if cur := p.ScreenShare; p.IsScreenSharing && cur != nil && eqPtr(cur.TrackSID, trackSID) && eqPtr(cur.TrackName, trackName) {
		return true, nil
	}
	now := platform.NowStr()
	track := models.ScreenShareTrackInfo{Active: true, Source: "screen_share", TrackSID: trackSID, TrackName: trackName, StartedAt: now}
	if err := s.Store.UpdateParticipant(ctx, roomID, participantID, map[string]any{"is_screen_sharing": true, "screen_share": track, "last_seen_at": now}); err != nil {
		return false, err
	}
	updated, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil || updated == nil {
		return false, err
	}
	_ = s.Publish(ctx, "participant.updated", roomID, updated)
	_ = s.Publish(ctx, "screen_share.started", roomID, map[string]any{
		"participant_id": updated.ParticipantID, "display_name": updated.DisplayName,
		"track_sid": trackSID, "track_name": trackName, "active": true, "timestamp": now, "source": "screen_share",
	})
	return true, nil
}

func eqPtr(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

// StopScreenShare mirrors stop_screen_share.
func (s *Service) StopScreenShare(ctx context.Context, roomID, participantID, sessionID, reason string) (bool, error) {
	p, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil {
		return false, err
	}
	if p == nil {
		return false, ErrParticipantNotFound
	}
	if sessionID != "" && p.SessionID != sessionID {
		return false, nil
	}
	if !p.IsScreenSharing {
		return true, nil
	}
	previous := p.ScreenShare
	now := platform.NowStr()
	if err := s.Store.UpdateParticipant(ctx, roomID, participantID, map[string]any{"is_screen_sharing": false, "screen_share": nil, "last_seen_at": now}); err != nil {
		return false, err
	}
	updated, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil || updated == nil {
		return false, err
	}
	_ = s.Publish(ctx, "participant.updated", roomID, updated)
	var trackSID, trackName any
	source := "screen_share"
	if previous != nil {
		trackSID, trackName = ptrAny(previous.TrackSID), ptrAny(previous.TrackName)
		source = previous.Source
	}
	_ = s.Publish(ctx, "screen_share.stopped", roomID, map[string]any{
		"participant_id": p.ParticipantID, "display_name": p.DisplayName, "track_sid": trackSID, "track_name": trackName,
		"active": false, "timestamp": now, "reason": reason, "source": source,
	})
	return true, nil
}

func ptrAny(p *string) any {
	if p == nil {
		return nil
	}
	return *p
}

// ── Presence / language ───────────────────────────────────────────────────

func (s *Service) TouchPresence(ctx context.Context, roomID, participantID, sessionID string, wsConnected *bool, status string) bool {
	p, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil || p == nil {
		return false
	}
	if sessionID != "" && p.SessionID != sessionID {
		return false
	}
	patch := map[string]any{"last_seen_at": platform.NowStr()}
	if wsConnected != nil {
		patch["ws_connected"] = *wsConnected
	}
	if status != "" {
		patch["status"] = status
	}
	return s.Store.UpdateParticipant(ctx, roomID, participantID, patch) == nil
}

// SetLanguage mirrors RoomService.set_language.
func (s *Service) SetLanguage(ctx context.Context, roomID, participantID string, language any) error {
	room, err := s.Store.GetRoomState(ctx, roomID)
	if err != nil {
		return err
	}
	if room == nil {
		return ErrRoomNotFound
	}
	langs := roomLanguages(room)
	code, _ := language.(string)
	if code == "auto" || !contains(langs, code) {
		return invalidRoomLanguage(langs)
	}
	p, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil {
		return err
	}
	if p == nil {
		return ErrParticipantNotFound
	}
	if err := s.Store.UpdateParticipant(ctx, roomID, participantID, map[string]any{"language": code}); err != nil {
		return err
	}
	updated, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil || updated == nil {
		return err
	}
	return s.Publish(ctx, "participant.updated", roomID, updated)
}

// ClearMutedByHost: the muted participant turned their own microphone back on.
func (s *Service) ClearMutedByHost(ctx context.Context, roomID, participantID, sessionID string) {
	p, err := s.Store.GetParticipant(ctx, roomID, participantID)
	if err != nil || p == nil || !p.MutedByHost {
		return
	}
	if sessionID != "" && p.SessionID != sessionID {
		return
	}
	if err := s.Store.UpdateParticipant(ctx, roomID, participantID, map[string]any{"muted_by_host": false}); err != nil {
		return
	}
	if updated, _ := s.Store.GetParticipant(ctx, roomID, participantID); updated != nil {
		_ = s.Publish(ctx, "participant.updated", roomID, updated)
	}
	_ = s.Publish(ctx, "moderation.participant_muted", roomID, map[string]any{
		"participant_id": participantID, "muted_by_host": false, "muted_by": p.DisplayName, "timestamp": platform.NowStr(),
	})
}

var _ = history.Participants
