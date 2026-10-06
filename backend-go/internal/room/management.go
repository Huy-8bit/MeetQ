package room

import (
	"context"
	"sort"

	"go.mongodb.org/mongo-driver/v2/bson"

	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
)

func (s *Service) SetRoomLocked(ctx context.Context, roomID string, locked bool, actorID, sessionID string) (*models.RoomResponse, error) {
	unlock := s.roomLock(ctx, roomID)
	defer unlock()
	snapshot, err := s.liveRoom(ctx, roomID)
	if err != nil {
		return nil, err
	}
	actor, err := s.activeActor(ctx, roomID, actorID, sessionID)
	if err != nil {
		return nil, err
	}
	if _, _, err := s.RequirePermission(ctx, roomID, actor.ParticipantID, PermLockRoom); err != nil {
		return nil, err
	}
	if snapshot.State.Locked == locked {
		resp := snapshot.State.Response()
		return &resp, nil
	}
	updated, err := s.Store.UpdateRoom(ctx, roomID, map[string]any{"locked": locked})
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, ErrRoomNotFound
	}
	now := platform.NowStr()
	_ = s.Publish(ctx, "room.lock_changed", roomID, map[string]any{
		"room_id": roomID, "locked": locked, "changed_by": actor.ParticipantID, "changed_by_name": actor.DisplayName, "changed_at": now,
	})
	s.History.Schedule(ctx, "room_lock_changed", roomID, func(c context.Context) error {
		return s.History.PersistRoomFlags(c, roomID, bson.M{"locked": locked})
	})
	action := "room_unlocked"
	if locked {
		action = "room_locked"
	}
	s.audit(ctx, action, roomID, "actor", actor.ParticipantID)
	resp := updated.Response()
	return &resp, nil
}

// SetRoomPassword sets/replaces (password) or removes (nil) the password. Host only.
func (s *Service) SetRoomPassword(ctx context.Context, roomID string, password *string, actorID, sessionID string) (*models.RoomResponse, error) {
	unlock := s.roomLock(ctx, roomID)
	defer unlock()
	if _, err := s.liveRoom(ctx, roomID); err != nil {
		return nil, err
	}
	actor, err := s.activeActor(ctx, roomID, actorID, sessionID)
	if err != nil {
		return nil, err
	}
	if _, _, err := s.RequirePermission(ctx, roomID, actor.ParticipantID, PermManagePassword); err != nil {
		return nil, err
	}
	if password != nil {
		// Replacing the hash invalidates the old password at once.
		if err := s.Access.SetPassword(ctx, roomID, *password); err != nil {
			return nil, err
		}
	} else if err := s.Access.Delete(ctx, roomID); err != nil {
		return nil, err
	}
	required := password != nil
	updated, err := s.Store.UpdateRoom(ctx, roomID, map[string]any{"password_required": required})
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, ErrRoomNotFound
	}
	_ = s.Publish(ctx, "room.access_updated", roomID, map[string]any{
		"room_id": roomID, "password_required": required, "changed_by": actor.ParticipantID,
		"changed_by_name": actor.DisplayName, "changed_at": platform.NowStr(),
	})
	s.History.Schedule(ctx, "room_access_updated", roomID, func(c context.Context) error {
		return s.History.PersistRoomFlags(c, roomID, bson.M{"password_required": required})
	})
	action := "room_password_removed"
	if required {
		action = "room_password_changed"
	}
	s.audit(ctx, action, roomID, "actor", actor.ParticipantID)
	resp := updated.Response()
	return &resp, nil
}

func (s *Service) moderationTarget(ctx context.Context, roomID string, actor *models.ParticipantState, targetID string) (*models.ParticipantState, string, string, error) {
	target, err := s.Store.GetParticipant(ctx, roomID, targetID)
	if err != nil {
		return nil, "", "", err
	}
	if target == nil || target.Status == "disconnected" || target.IsVirtual {
		return nil, "", "", &ActionError{Status: 404, Code: "participant_not_found", Message: "Participant not found in room"}
	}
	if target.ParticipantID == actor.ParticipantID {
		return nil, "", "", &ActionError{Status: 422, Code: "cannot_target_self", Message: "You can't do this to yourself."}
	}
	targetUser, targetRole := s.ParticipantRole(ctx, roomID, target.ParticipantID)
	actorUser, actorRole := s.ParticipantRole(ctx, roomID, actor.ParticipantID)
	if targetUser != "" && targetUser == actorUser {
		return nil, "", "", &ActionError{Status: 422, Code: "cannot_target_self", Message: "You can't do this to yourself."}
	}
	// Nobody acts on the host; co-hosts act on participants only.
	if !Outranks(actorRole, targetRole) {
		s.audit(ctx, "permission_denied", roomID, "actor", actor.ParticipantID, "target", target.ParticipantID, "reason", "target_role")
		return nil, "", "", ErrPermissionDenied()
	}
	return target, targetUser, targetRole, nil
}

func (s *Service) MuteParticipant(ctx context.Context, roomID, targetID, actorID, sessionID string) (map[string]any, error) {
	if _, err := s.liveRoom(ctx, roomID); err != nil {
		return nil, err
	}
	actor, err := s.activeActor(ctx, roomID, actorID, sessionID)
	if err != nil {
		return nil, err
	}
	if _, _, err := s.RequirePermission(ctx, roomID, actor.ParticipantID, PermMuteParticipant); err != nil {
		return nil, err
	}
	target, _, _, err := s.moderationTarget(ctx, roomID, actor, targetID)
	if err != nil {
		return nil, err
	}
	// Enforced on the SFU when LiveKit is reachable; the client is also told to mute.
	identity := target.ParticipantID
	if target.LiveKitIdentity != nil && *target.LiveKitIdentity != "" {
		identity = *target.LiveKitIdentity
	}
	providerMuted := s.LiveKit != nil && s.LiveKit.MuteMicrophone(ctx, roomID, identity)
	now := platform.NowStr()
	_ = s.Store.UpdateParticipant(ctx, roomID, target.ParticipantID, map[string]any{"muted_by_host": true})
	if updated, _ := s.Store.GetParticipant(ctx, roomID, target.ParticipantID); updated != nil {
		_ = s.Publish(ctx, "participant.updated", roomID, updated)
	}
	_ = s.Publish(ctx, "moderation.participant_muted", roomID, map[string]any{
		"participant_id": target.ParticipantID, "muted_by_host": true, "muted_by": actor.DisplayName,
		"muted_by_participant_id": actor.ParticipantID, "timestamp": now,
	})
	s.audit(ctx, "participant_muted", roomID, "actor", actor.ParticipantID, "target", target.ParticipantID, "provider_muted", providerMuted)
	return map[string]any{"participant_id": target.ParticipantID, "muted_by_host": true, "provider_muted": providerMuted, "timestamp": now}, nil
}

func (s *Service) RemoveParticipant(ctx context.Context, roomID, targetID, actorID, sessionID string) (map[string]any, error) {
	if _, err := s.liveRoom(ctx, roomID); err != nil {
		return nil, err
	}
	actor, err := s.activeActor(ctx, roomID, actorID, sessionID)
	if err != nil {
		return nil, err
	}
	actorUser, _, err := s.RequirePermission(ctx, roomID, actor.ParticipantID, PermRemoveParticipant)
	if err != nil {
		return nil, err
	}
	target, targetUser, _, err := s.moderationTarget(ctx, roomID, actor, targetID)
	if err != nil {
		return nil, err
	}
	now := platform.NowStr()
	sessions := map[string]bool{target.ParticipantID: true}
	if targetUser != "" {
		var removedBy any
		if actorUser != "" {
			removedBy = actorUser
		}
		if err := s.Members.Update(ctx, roomID, targetUser, map[string]any{"removed_at": now, "removed_by_user_id": removedBy}); err != nil {
			return nil, err
		}
		others, _ := s.Members.ParticipantsForUser(ctx, roomID, targetUser)
		for _, id := range others {
			sessions[id] = true
		}
		s.History.Schedule(ctx, "membership_removed", roomID, func(c context.Context) error {
			return s.History.PersistMembershipRemoved(c, roomID, targetUser, now, actorUser)
		})
	}
	ids := make([]string, 0, len(sessions))
	for id := range sessions {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	removed := 0
	for _, participantID := range ids {
		p, _ := s.Store.GetParticipant(ctx, roomID, participantID)
		if p == nil || p.Status == "disconnected" {
			continue
		}
		// Everyone is told first; each gateway then closes the removed websocket (4409).
		_ = s.Publish(ctx, "participant.removed", roomID, map[string]any{
			"participant_id": participantID, "removed_by": actor.DisplayName, "removed_by_participant_id": actor.ParticipantID,
			"removed_at": now, "reason": "removed_by_host",
		})
		identity := participantID
		if p.LiveKitIdentity != nil && *p.LiveKitIdentity != "" {
			identity = *p.LiveKitIdentity
		}
		if s.LiveKit != nil {
			s.LiveKit.RemoveParticipant(ctx, roomID, identity)
		}
		s.CleanupParticipant(ctx, roomID, participantID, "", "removed_by_host")
		removed++
	}
	s.audit(ctx, "participant_removed", roomID, "actor", actor.ParticipantID, "target", target.ParticipantID, "sessions", removed)
	return map[string]any{"participant_id": target.ParticipantID, "removed": true, "removed_at": now}, nil
}

func (s *Service) SetParticipantRole(ctx context.Context, roomID, targetID, role, actorID, sessionID string) (map[string]any, error) {
	if role != models.RoleCoHost && role != models.RoleParticipant {
		return nil, &ActionError{Status: 422, Code: "invalid_role", Message: "Role must be co_host or participant."}
	}
	unlock := s.roomLock(ctx, roomID)
	defer unlock()
	if _, err := s.liveRoom(ctx, roomID); err != nil {
		return nil, err
	}
	actor, err := s.activeActor(ctx, roomID, actorID, sessionID)
	if err != nil {
		return nil, err
	}
	if _, _, err := s.RequirePermission(ctx, roomID, actor.ParticipantID, PermAssignCoHost); err != nil {
		return nil, err
	}
	target, targetUser, oldRole, err := s.moderationTarget(ctx, roomID, actor, targetID)
	if err != nil {
		return nil, err
	}
	if targetUser == "" {
		return nil, &ActionError{Status: 409, Code: "participant_not_signed_in", Message: "This participant has no MeetQ account."}
	}
	if oldRole == role {
		return map[string]any{"participant_id": target.ParticipantID, "role": role, "changed": false}, nil
	}
	if err := s.Members.Update(ctx, roomID, targetUser, map[string]any{"role": role}); err != nil {
		return nil, err
	}
	now := platform.NowStr()
	sessions, _ := s.Members.ParticipantsForUser(ctx, roomID, targetUser)
	sort.Strings(sessions)
	updatedIDs := []string{}
	for _, participantID := range sessions {
		p, _ := s.Store.GetParticipant(ctx, roomID, participantID)
		if p == nil || p.Status == "disconnected" {
			continue
		}
		_ = s.Store.UpdateParticipant(ctx, roomID, participantID, map[string]any{"role": role})
		if updated, _ := s.Store.GetParticipant(ctx, roomID, participantID); updated != nil {
			_ = s.Publish(ctx, "participant.updated", roomID, updated)
		}
		updatedIDs = append(updatedIDs, participantID)
	}
	_ = s.Publish(ctx, "participant.role_changed", roomID, map[string]any{
		"room_id": roomID, "participant_id": target.ParticipantID, "participant_ids": updatedIDs,
		"old_role": oldRole, "new_role": role, "changed_by": actor.ParticipantID,
		"changed_by_name": actor.DisplayName, "changed_at": now,
	})
	s.History.Schedule(ctx, "membership_role_changed", roomID, func(c context.Context) error {
		return s.History.PersistMembership(c, roomID, targetUser, membershipRole(role))
	})
	action := "cohost_removed"
	if role == models.RoleCoHost {
		action = "cohost_assigned"
	}
	s.audit(ctx, action, roomID, "actor", actor.ParticipantID, "target", target.ParticipantID)
	return map[string]any{"participant_id": target.ParticipantID, "role": role, "changed": true}, nil
}

func membershipRole(role string) history.MembershipFields {
	return history.MembershipFields{Role: role}
}
