package room

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"meetq/backend-go/internal/ai"
	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/httpx"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
)

type Handler struct {
	Service *Service
	Auth    *auth.Service
	Cfg     *config.Config
}

func NewHandler(s *Service, a *auth.Service, cfg *config.Config) *Handler {
	return &Handler{
		Service: s,
		Auth:    a,
		Cfg:     cfg,
	}
}

func (h *Handler) Register(mux *http.ServeMux) {
	mux.Handle("POST /api/rooms", httpx.Handler(h.createRoom))
	mux.Handle("GET /api/rooms/{room_id}", httpx.Handler(h.getRoom))
	mux.Handle("GET /api/rooms/{room_id}/summary", httpx.Handler(h.getRoomSummary))
	mux.Handle("POST /api/rooms/{room_id}/summary", httpx.Handler(h.generateRoomSummary))
	mux.Handle("POST /api/rooms/{room_id}/join", httpx.Handler(h.joinRoom))
	mux.Handle("POST /api/rooms/{room_id}/brse/enable", httpx.Handler(h.enableBrse))
	mux.Handle("POST /api/rooms/{room_id}/brse/disable", httpx.Handler(h.disableBrse))
	mux.Handle("PATCH /api/rooms/{room_id}/relay-mode", httpx.Handler(h.updateRelayMode))
	mux.Handle("DELETE /api/rooms/{room_id}/leave", httpx.Handler(h.leaveRoom))
	mux.Handle("POST /api/rooms/{room_id}/screen-share/start", httpx.Handler(h.startScreenShare))
	mux.Handle("POST /api/rooms/{room_id}/screen-share/stop", httpx.Handler(h.stopScreenShare))
	mux.Handle("GET /api/rooms/{room_id}/permissions", httpx.Handler(h.getPermissions))
	mux.Handle("POST /api/rooms/{room_id}/lock", httpx.Handler(h.lockRoom))
	mux.Handle("POST /api/rooms/{room_id}/unlock", httpx.Handler(h.unlockRoom))
	mux.Handle("PATCH /api/rooms/{room_id}/password", httpx.Handler(h.changePassword))
	mux.Handle("DELETE /api/rooms/{room_id}/password", httpx.Handler(h.removePassword))
	mux.Handle("POST /api/rooms/{room_id}/participants/{target_participant_id}/mute", httpx.Handler(h.muteParticipant))
	mux.Handle("POST /api/rooms/{room_id}/moderation/mute", httpx.Handler(h.muteParticipantLegacy))
	mux.Handle("POST /api/rooms/{room_id}/participants/{target_participant_id}/remove", httpx.Handler(h.removeParticipant))
	mux.Handle("PATCH /api/rooms/{room_id}/participants/{target_participant_id}/role", httpx.Handler(h.updateParticipantRole))
}

func (h *Handler) sessionUser(r *http.Request) (string, error) {
	if !h.Cfg.UserAuthRequired {
		return "", nil
	}
	session, err := h.Auth.CurrentUser(r)
	if err != nil {
		return "", err
	}
	return auth.UserID(session), nil
}

func (h *Handler) mayReadProtectedRoom(ctx context.Context, roomID string, claims Claims, userID string) bool {
	if claims != nil {
		if h.Service.IsRemovedParticipant(ctx, roomID, claims.ParticipantID()) {
			return false
		}
		return true
	}
	isProtected, err := h.Service.IsPasswordProtected(ctx, roomID)
	if err != nil || !isProtected {
		return true
	}
	if userID == "" || h.Service.History == nil || !h.Service.History.Enabled() {
		return false
	}
	joined, _ := h.Service.History.UserJoinedRoom(ctx, roomID, userID)
	return joined
}

func (h *Handler) createRoom(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.sessionUser(r)
	if err != nil {
		return err
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil {
		errs := &httpx.ValidationError{}
		errs.Add([]any{"body", 0}, "json_invalid", "JSON decode error")
		return errs
	}

	input := CreateRoomInput{
		CreatedByUserID: userID,
		BrseEnabled:     models.DefaultBrseEnabled,
		BrseMode:        models.DefaultBrseMode,
		BrseOutputMode:  models.DefaultBrseOutputMode,
	}
	languagesProvided := false

	if body != nil {
		if rawLangs, ok := body["room_languages"].([]any); ok {
			languagesProvided = true
			langs := make([]string, 0, len(rawLangs))
			for _, l := range rawLangs {
				if s, ok := l.(string); ok {
					langs = append(langs, s)
				}
			}
			input.Languages = langs
		} else if rawMeetingLangs, ok := body["meeting_languages"].([]any); ok {
			languagesProvided = true
			langs := make([]string, 0, len(rawMeetingLangs))
			for _, l := range rawMeetingLangs {
				if s, ok := l.(string); ok {
					langs = append(langs, s)
				}
			}
			input.Languages = langs
		}

		if b, ok, _ := httpx.BodyBool(body, "brse_enabled"); ok {
			input.BrseEnabled = b
		}
		if s, ok, _ := httpx.BodyString(body, "brse_mode"); ok && s != "" {
			input.BrseMode = s
		}
		if s, ok, _ := httpx.BodyString(body, "brse_output_mode"); ok && s != "" {
			input.BrseOutputMode = s
		}
		if s, ok, _ := httpx.BodyString(body, "title"); ok && s != "" {
			input.Title = &s
		}
		if access, ok, _ := httpx.BodyString(body, "access"); ok && access == "password" {
			if pw, ok, _ := httpx.BodyString(body, "password"); ok {
				input.Password = &pw
			}
		}
	}

	resp, err := h.Service.CreateRoom(r.Context(), input, languagesProvided)
	if err != nil {
		var invalidLangs *InvalidMeetingLanguagesError
		if errors.As(err, &invalidLangs) {
			return httpx.NewError(422, "invalid_meeting_languages", invalidLangs.Message).WithDetails(invalidLangs.Details)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) getRoom(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	if roomID == "" {
		return httpx.NewError(404, "room_not_found", "Room not found")
	}

	_, err := h.sessionUser(r)
	if err != nil {
		return err
	}

	claims := OptionalToken(r, h.Cfg.RoomJWTSecret, roomID)
	if claims != nil && h.Service.IsRemovedParticipant(r.Context(), roomID, claims.ParticipantID()) {
		claims = nil
	}

	snapshot, err := h.Service.GetRoom(r.Context(), roomID, claims != nil)
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, snapshot)
	return nil
}

func (h *Handler) getRoomSummary(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	userID, err := h.sessionUser(r)
	if err != nil {
		return err
	}

	claims := OptionalToken(r, h.Cfg.RoomJWTSecret, roomID)
	if !h.mayReadProtectedRoom(r.Context(), roomID, claims, userID) {
		return httpx.NewError(404, "meeting_summary_not_found", "Meeting summary not found")
	}

	summaryType := r.URL.Query().Get("type")
	if summaryType == "" {
		summaryType = "final"
	}

	summary, err := h.Service.GetMeetingSummary(r.Context(), roomID, summaryType)
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) || errors.Is(err, ErrSummaryNotFound) {
			return httpx.NewError(404, "meeting_summary_not_found", "Meeting summary not found")
		}
		if errors.Is(err, ErrInvalidSummaryType) {
			return httpx.NewError(422, "invalid_summary_type", "summary type must be interim or final")
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, summary)
	return nil
}

func (h *Handler) generateRoomSummary(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	userID, err := h.sessionUser(r)
	if err != nil {
		return err
	}

	claims := OptionalToken(r, h.Cfg.RoomJWTSecret, roomID)
	if !h.mayReadProtectedRoom(r.Context(), roomID, claims, userID) {
		return httpx.NewError(404, "meeting_summary_not_found", "Meeting summary not found")
	}

	body, _, _ := httpx.DecodeJSON(r, 64<<10)
	var summaryType, language *string
	if body != nil {
		if st, ok, _ := httpx.BodyString(body, "type"); ok && st != "" {
			summaryType = &st
		}
		if l, ok, _ := httpx.BodyString(body, "language"); ok && l != "" {
			language = &l
		} else if sl, ok, _ := httpx.BodyString(body, "summary_language"); ok && sl != "" {
			language = &sl
		}
	}

	raw, err := h.Service.GenerateMeetingSummary(r.Context(), roomID, summaryType, language, claims)
	if err != nil {
		var aiErr *ai.Error
		if errors.As(err, &aiErr) {
			return httpx.NewError(aiErr.Status, aiErr.Code, aiErr.Message).WithDetails(aiErr.Details)
		}
		if errors.Is(err, ai.ErrUnavailable) {
			return httpx.NewError(503, "meeting_summary_unavailable", "Meeting summary persistence is unavailable")
		}
		return err
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(raw)
	return nil
}

func (h *Handler) joinRoom(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	userID, err := h.sessionUser(r)
	if err != nil {
		return err
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	errs := &httpx.ValidationError{}
	if err != nil {
		errs.Add([]any{"body", 0}, "json_invalid", "JSON decode error")
		return errs
	}
	if body == nil {
		errs.Add([]any{"body"}, "missing", "Field required")
		return errs
	}

	displayName, hasName, _ := httpx.BodyString(body, "display_name")
	if !hasName || strings.TrimSpace(displayName) == "" {
		errs.Add([]any{"body", "display_name"}, "missing", "Field required")
	}

	language, hasLang, _ := httpx.BodyString(body, "language")
	if !hasLang || strings.TrimSpace(language) == "" {
		errs.Add([]any{"body", "language"}, "missing", "Field required")
	}

	if !errs.Empty() {
		return errs
	}

	clientMeta, _ := body["client"].(map[string]any)
	var password *string
	if pw, ok, _ := httpx.BodyString(body, "password"); ok {
		password = &pw
	}

	input := JoinInput{
		DisplayName: strings.TrimSpace(displayName),
		Language:    strings.TrimSpace(language),
		Client:      clientMeta,
		UserID:      userID,
		Password:    password,
		ClientIP:    auth.ClientKey(r),
	}

	resp, err := h.Service.JoinRoom(r.Context(), roomID, input)
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		if errors.Is(err, ErrParticipantRemoved) {
			return httpx.NewError(403, "removed_from_room", "You were removed from this meeting.")
		}
		if errors.Is(err, ErrRoomLocked) {
			return httpx.NewError(403, "room_locked", "This meeting is locked by the host.")
		}
		if errors.Is(err, ErrPasswordRequired) {
			return httpx.NewError(403, "room_password_required", "This meeting requires a password.")
		}
		if errors.Is(err, ErrInvalidPassword) {
			return httpx.NewError(403, "invalid_room_password", "Incorrect meeting password.")
		}
		var rateLimited *PasswordRateLimitedError
		if errors.As(err, &rateLimited) {
			apiErr := httpx.NewError(429, "room_password_rate_limited", "Too many incorrect password attempts. Please wait a few minutes and try again.")
			apiErr.Headers = map[string]string{"Retry-After": "300"}
			return apiErr
		}
		if errors.Is(err, ErrRoomExpired) {
			return httpx.NewError(410, "room_expired", "Room meeting duration has expired. Please create a new room.")
		}
		if errors.Is(err, ErrRoomFull) {
			return httpx.NewError(409, "room_full", "Room is full")
		}
		var invalidLang *InvalidLanguageError
		if errors.As(err, &invalidLang) {
			return httpx.NewError(422, "invalid_language", invalidLang.Message).WithDetails(invalidLang.Details)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) verifyActor(r *http.Request, roomID string) (Claims, error) {
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return nil, httpx.ErrNotAuthenticated
	}
	if h.Cfg.UserAuthRequired {
		session, err := h.Auth.CurrentUser(r)
		if err != nil {
			return nil, err
		}
		signedInUser := auth.UserID(session)
		if signedInUser != "" {
			tokenUser, _ := h.Service.Members.UserForParticipant(r.Context(), roomID, claims.ParticipantID())
			if tokenUser != "" && tokenUser != signedInUser {
				return nil, ErrPermissionDenied()
			}
		}
	}
	return claims, nil
}

func (h *Handler) enableBrse(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	resp, err := h.Service.SetBrseEnabled(r.Context(), roomID, true, claims.ParticipantID(), claims.SessionID(), "rest_enable")
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		var brseErr *BrseForbiddenError
		if errors.As(err, &brseErr) {
			status := 403
			if brseErr.Code == "session_mismatch" {
				status = 409
			}
			return httpx.NewError(status, brseErr.Code, brseErr.Message)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) disableBrse(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	resp, err := h.Service.SetBrseEnabled(r.Context(), roomID, false, claims.ParticipantID(), claims.SessionID(), "rest_disable")
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		var brseErr *BrseForbiddenError
		if errors.As(err, &brseErr) {
			status := 403
			if brseErr.Code == "session_mismatch" {
				status = 409
			}
			return httpx.NewError(status, brseErr.Code, brseErr.Message)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) updateRelayMode(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil || body == nil {
		return httpx.NewError(422, "validation_error", "Invalid request body")
	}
	mode, ok, _ := httpx.BodyString(body, "mode")
	if !ok || mode == "" {
		return httpx.NewError(422, "validation_error", "mode is required")
	}

	resp, err := h.Service.SetRelayMode(r.Context(), roomID, mode, claims.ParticipantID(), claims.SessionID(), "rest_relay_mode")
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		if errors.Is(err, ErrRoomExpired) {
			return httpx.NewError(409, "room_expired", "This meeting has ended.")
		}
		var relayErr *RelayModeNotSupportedError
		if errors.As(err, &relayErr) {
			return httpx.NewError(422, "unsupported_relay_mode", relayErr.Message)
		}
		var brseErr *BrseForbiddenError
		if errors.As(err, &brseErr) {
			status := 403
			if brseErr.Code == "session_mismatch" {
				status = 409
			}
			return httpx.NewError(status, brseErr.Code, brseErr.Message)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) leaveRoom(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	h.Service.LeaveRoom(r.Context(), roomID, claims.ParticipantID(), claims.SessionID())
	httpx.NoContent(w)
	return nil
}

func (h *Handler) startScreenShare(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	var trackSID, trackName *string
	if body != nil {
		if s, ok, _ := httpx.BodyString(body, "track_sid"); ok && s != "" {
			trackSID = &s
		}
		if s, ok, _ := httpx.BodyString(body, "track_name"); ok && s != "" {
			trackName = &s
		}
	}

	ok, err := h.Service.StartScreenShare(r.Context(), roomID, claims.ParticipantID(), claims.SessionID(), trackSID, trackName)
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		if errors.Is(err, ErrParticipantNotFound) {
			return httpx.NewError(404, "participant_not_found", "Participant not found in room")
		}
		return err
	}
	if !ok {
		return httpx.NewError(409, "session_mismatch", "Session no longer valid for participant")
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"participant_id": claims.ParticipantID(),
		"display_name":   claims.String("display_name"),
		"active":         true,
		"timestamp":      platform.NowStr(),
		"track_sid":      trackSID,
		"track_name":     trackName,
	})
	return nil
}

func (h *Handler) stopScreenShare(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	ok, err := h.Service.StopScreenShare(r.Context(), roomID, claims.ParticipantID(), claims.SessionID(), "rest_stop")
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found")
		}
		if errors.Is(err, ErrParticipantNotFound) {
			return httpx.NewError(404, "participant_not_found", "Participant not found in room")
		}
		return err
	}
	if !ok {
		return httpx.NewError(409, "session_mismatch", "Session no longer valid for participant")
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"participant_id": claims.ParticipantID(),
		"display_name":   claims.String("display_name"),
		"active":         false,
		"timestamp":      platform.NowStr(),
	})
	return nil
}

func (h *Handler) getPermissions(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	perms, err := h.Service.GetPermissions(r.Context(), roomID, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, perms)
	return nil
}

func (h *Handler) lockRoom(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	resp, err := h.Service.SetRoomLocked(r.Context(), roomID, true, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) unlockRoom(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	resp, err := h.Service.SetRoomLocked(r.Context(), roomID, false, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) changePassword(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil || body == nil {
		return httpx.NewError(422, "validation_error", "Invalid request body")
	}
	pw, ok, _ := httpx.BodyString(body, "password")
	if !ok || strings.TrimSpace(pw) == "" {
		return httpx.NewError(422, "validation_error", "password is required")
	}

	resp, err := h.Service.SetRoomPassword(r.Context(), roomID, &pw, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) removePassword(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	resp, err := h.Service.SetRoomPassword(r.Context(), roomID, nil, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) muteParticipant(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	targetID := r.PathValue("target_participant_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	resp, err := h.Service.MuteParticipant(r.Context(), roomID, targetID, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) muteParticipantLegacy(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil || body == nil {
		return httpx.NewError(422, "validation_error", "Invalid request body")
	}
	targetID, ok, _ := httpx.BodyString(body, "target_participant_id")
	if !ok || targetID == "" {
		return httpx.NewError(422, "validation_error", "target_participant_id is required")
	}

	resp, err := h.Service.MuteParticipant(r.Context(), roomID, targetID, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) removeParticipant(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	targetID := r.PathValue("target_participant_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	resp, err := h.Service.RemoveParticipant(r.Context(), roomID, targetID, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) updateParticipantRole(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	targetID := r.PathValue("target_participant_id")
	claims, err := h.verifyActor(r, roomID)
	if err != nil {
		return err
	}

	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil || body == nil {
		return httpx.NewError(422, "validation_error", "Invalid request body")
	}
	role, ok, _ := httpx.BodyString(body, "role")
	if !ok || role == "" {
		return httpx.NewError(422, "validation_error", "role is required")
	}

	resp, err := h.Service.SetParticipantRole(r.Context(), roomID, targetID, role, claims.ParticipantID(), claims.SessionID())
	if err != nil {
		return h.mapManageError(err)
	}

	httpx.JSON(w, http.StatusOK, resp)
	return nil
}

func (h *Handler) mapManageError(err error) error {
	if errors.Is(err, ErrRoomNotFound) {
		return httpx.NewError(404, "room_not_found", "Room not found")
	}
	if errors.Is(err, ErrRoomExpired) {
		return httpx.NewError(409, "room_expired", "This meeting has ended.")
	}
	var permErr *PermissionError
	if errors.As(err, &permErr) {
		return httpx.NewError(403, permErr.Code, permErr.Message)
	}
	var actErr *ActionError
	if errors.As(err, &actErr) {
		return httpx.NewError(actErr.Status, actErr.Code, actErr.Message)
	}
	return err
}
