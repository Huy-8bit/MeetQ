package archive

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"time"

	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/httpx"
	"meetq/backend-go/internal/room"
)

type MeetingAccessChecker interface {
	CheckAccess(ctx context.Context, roomID, userID string) error
}

type Handler struct {
	Service       *Service
	Auth          *auth.Service
	Cfg           *config.Config
	RoomService   *room.Service
	MeetingAccess MeetingAccessChecker
}

func NewHandler(s *Service, a *auth.Service, cfg *config.Config, rs *room.Service, ma MeetingAccessChecker) *Handler {
	return &Handler{
		Service:       s,
		Auth:          a,
		Cfg:           cfg,
		RoomService:   rs,
		MeetingAccess: ma,
	}
}

func (h *Handler) Register(mux *http.ServeMux) {
	mux.Handle("POST /api/rooms/{room_id}/recordings", httpx.Handler(h.startRecording))
	mux.Handle("POST /api/rooms/{room_id}/recordings/{recording_id}/stop", httpx.Handler(h.stopRecording))
	mux.Handle("GET /api/rooms/{room_id}/recordings/current", httpx.Handler(h.currentRecording))
	mux.Handle("GET /api/recordings/{recording_id}", httpx.Handler(h.getRecording))
	mux.Handle("POST /api/recordings/{recording_id}/playback-url", httpx.Handler(h.playbackURL))
	mux.Handle("POST /api/recordings/{recording_id}/download-url", httpx.Handler(h.downloadURL))

	// Admin recording & archive routes
	mux.Handle("GET /api/admin/recordings", httpx.Handler(h.adminListRecordings))
	mux.Handle("GET /api/admin/archives/{archive_id}", httpx.Handler(h.adminGetArchive))
	mux.Handle("GET /api/admin/settings/retention", httpx.Handler(h.adminGetRetention))
	mux.Handle("PATCH /api/admin/settings/retention", httpx.Handler(h.adminUpdateRetention))
	mux.Handle("PATCH /api/admin/archives/{archive_id}/retention", httpx.Handler(h.adminUpdateArchiveRetention))
	mux.Handle("DELETE /api/admin/archives/{archive_id}", httpx.Handler(h.adminDeleteArchive))
}

func (h *Handler) requireUser(r *http.Request) (string, error) {
	session, err := h.Auth.RequireUser(r)
	if err != nil {
		return "", err
	}
	return auth.UserID(session), nil
}

func (h *Handler) requireAdmin(r *http.Request) (string, error) {
	session, err := h.Auth.RequireAdmin(r)
	if err != nil {
		return "", err
	}
	return auth.AdminName(session), nil
}

func (h *Handler) roomParticipant(r *http.Request, roomID string) (room.Claims, error) {
	claims, err := room.RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return nil, httpx.ErrNotAuthenticated
	}
	pid := claims.ParticipantID()
	p, err := h.RoomService.Store.GetParticipant(r.Context(), roomID, pid)
	if err != nil || p == nil || p.IsVirtual || p.Kind != "human" {
		return nil, httpx.NewError(403, "not_in_room", "Join the meeting to control recording.")
	}
	return claims, nil
}

func (h *Handler) requireRecordingPermission(r *http.Request, roomID, participantID string) error {
	_, _, err := h.RoomService.RequirePermission(r.Context(), roomID, participantID, "recording")
	if err != nil {
		return httpx.NewError(403, "permission_denied", "You don't have permission to control recording.")
	}
	return nil
}

func (h *Handler) startRecording(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}

	claims, err := h.roomParticipant(r, roomID)
	if err != nil {
		return err
	}
	if err := h.requireRecordingPermission(r, roomID, claims.ParticipantID()); err != nil {
		return err
	}

	snapshot, err := h.RoomService.Store.GetRoomSnapshot(r.Context(), roomID, false)
	if err != nil || snapshot == nil {
		return httpx.NewError(404, "room_not_found", "Room not found.")
	}

	var langs []string
	if snapshot.State != nil {
		langs = snapshot.State.RoomLanguages
	}

	state, err := h.Service.Start(
		r.Context(),
		roomID,
		claims.ParticipantID(),
		claims.String("display_name"),
		userID,
		langs,
	)
	if err != nil {
		var recErr *RecordingError
		if errors.As(err, &recErr) {
			return httpx.NewError(recErr.Status, recErr.Code, recErr.Message)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"recording": state})
	return nil
}

func (h *Handler) stopRecording(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	recordingID := r.PathValue("recording_id")
	_, err := h.requireUser(r)
	if err != nil {
		return err
	}

	claims, err := h.roomParticipant(r, roomID)
	if err != nil {
		return err
	}
	if err := h.requireRecordingPermission(r, roomID, claims.ParticipantID()); err != nil {
		return err
	}

	state, err := h.Service.Stop(
		r.Context(),
		roomID,
		recordingID,
		"user_stopped",
		claims.String("display_name"),
	)
	if err != nil {
		var recErr *RecordingError
		if errors.As(err, &recErr) {
			return httpx.NewError(recErr.Status, recErr.Code, recErr.Message)
		}
		return err
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"recording": state})
	return nil
}

func (h *Handler) currentRecording(w http.ResponseWriter, r *http.Request) error {
	roomID := r.PathValue("room_id")
	_, err := h.requireUser(r)
	if err != nil {
		return err
	}
	_, err = room.RequireToken(r, h.Cfg.RoomJWTSecret, roomID)
	if err != nil {
		return httpx.ErrNotAuthenticated
	}

	rec, err := h.Service.Current(r.Context(), roomID)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"recording": rec,
		"available": h.Service.Available(),
	})
	return nil
}

func (h *Handler) recordingForUser(r *http.Request, recordingID string) (map[string]any, error) {
	if !h.Service.Repo.Enabled() {
		return nil, httpx.NewError(503, "history_unavailable", "Meeting history is not available on this server.")
	}
	doc, err := h.Service.Repo.GetRecording(r.Context(), recordingID)
	if err != nil || doc == nil {
		return nil, httpx.NewError(404, "recording_not_found", "Recording not found.")
	}
	roomID, _ := doc["room_id"].(string)
	if h.MeetingAccess != nil {
		session, err := h.Auth.CurrentUser(r)
		if err != nil {
			return nil, err
		}
		userID := auth.UserID(session)
		if err := h.MeetingAccess.CheckAccess(r.Context(), roomID, userID); err != nil {
			return nil, err
		}
	}
	return doc, nil
}

func (h *Handler) getRecording(w http.ResponseWriter, r *http.Request) error {
	recordingID := r.PathValue("recording_id")
	doc, err := h.recordingForUser(r, recordingID)
	if err != nil {
		return err
	}
	pub := PublicRecording(doc)
	pub["playable"] = doc["status"] == RecReady
	httpx.JSON(w, http.StatusOK, map[string]any{"recording": pub})
	return nil
}

func (h *Handler) signedURL(w http.ResponseWriter, r *http.Request, recordingID string, download bool) error {
	doc, err := h.recordingForUser(r, recordingID)
	if err != nil {
		return err
	}
	if doc["status"] != RecReady {
		return httpx.NewError(409, "recording_not_ready", "The recording is still being prepared.")
	}
	if h.Service.Storage == nil {
		return httpx.NewError(503, "recording_unavailable", "Recording storage is not configured.")
	}

	ttl := h.Cfg.RecordingURLTTLSeconds
	if ttl < 60 {
		ttl = 60
	} else if ttl > 3600 {
		ttl = 3600
	}

	var downloadName *string
	if download {
		name := fmt.Sprintf("meetq-%s-%s.mp4", doc["room_id"], doc["_id"])
		downloadName = &name
	}

	s3Key, _ := doc["s3_key"].(string)
	presignedURL, err := h.Service.Storage.PresignedGetURL(r.Context(), s3Key, time.Duration(ttl)*time.Second, downloadName)
	if err != nil {
		return httpx.NewError(500, "storage_error", "Failed to generate presigned URL")
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"url":        presignedURL,
		"expires_in": ttl,
	})
	return nil
}

func (h *Handler) playbackURL(w http.ResponseWriter, r *http.Request) error {
	return h.signedURL(w, r, r.PathValue("recording_id"), false)
}

func (h *Handler) downloadURL(w http.ResponseWriter, r *http.Request) error {
	return h.signedURL(w, r, r.PathValue("recording_id"), true)
}

// ── Admin routes ────────────────────────────────────────────────────────────

func (h *Handler) adminListRecordings(w http.ResponseWriter, r *http.Request) error {
	if _, err := h.requireAdmin(r); err != nil {
		return err
	}
	query := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(query, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 20, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(query, errs)
	status, _ := httpx.QueryString(query, "status")
	if !errs.Empty() {
		return errs
	}

	var statusPtr *string
	if status != "" {
		statusPtr = &status
	}
	items, total, err := h.Service.Repo.ListAllRecordings(r.Context(), statusPtr, page, pageSize)
	if err != nil {
		return err
	}

	publicItems := make([]map[string]any, 0, len(items))
	for _, it := range items {
		publicItems = append(publicItems, PublicRecording(it))
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"items":     publicItems,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
	return nil
}

func (h *Handler) adminGetArchive(w http.ResponseWriter, r *http.Request) error {
	if _, err := h.requireAdmin(r); err != nil {
		return err
	}
	archiveID := r.PathValue("archive_id")
	doc, err := h.Service.Repo.GetArchive(r.Context(), archiveID)
	if err != nil || doc == nil {
		return httpx.NewError(404, "archive_not_found", "Archive not found.")
	}
	httpx.JSON(w, http.StatusOK, doc)
	return nil
}

func (h *Handler) adminGetRetention(w http.ResponseWriter, r *http.Request) error {
	if _, err := h.requireAdmin(r); err != nil {
		return err
	}
	res, err := h.Service.Repo.GetRetentionSettings(r.Context())
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) adminUpdateRetention(w http.ResponseWriter, r *http.Request) error {
	adminUser, err := h.requireAdmin(r)
	if err != nil {
		return err
	}
	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil || body == nil {
		return httpx.NewError(422, "validation_error", "Invalid request body")
	}
	days, ok, _ := httpx.BodyInt(body, "default_retention_days")
	if !ok || days < 1 || days > 365 {
		return httpx.NewError(422, "invalid_retention_days", "default_retention_days must be between 1 and 365.")
	}

	res, err := h.Service.Repo.UpdateRetentionSettings(r.Context(), days, adminUser)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) adminUpdateArchiveRetention(w http.ResponseWriter, r *http.Request) error {
	adminUser, err := h.requireAdmin(r)
	if err != nil {
		return err
	}
	archiveID := r.PathValue("archive_id")
	body, _, err := httpx.DecodeJSON(r, 64<<10)
	if err != nil || body == nil {
		return httpx.NewError(422, "validation_error", "Invalid request body")
	}
	days, ok, _ := httpx.BodyInt(body, "retention_days")
	if !ok || days < 1 || days > 365 {
		return httpx.NewError(422, "invalid_retention_days", "retention_days must be between 1 and 365.")
	}

	res, err := h.Service.Repo.UpdateArchiveRetention(r.Context(), archiveID, days, adminUser)
	if err != nil {
		if errors.Is(err, ErrArchiveNotFound) {
			return httpx.NewError(404, "archive_not_found", "Archive not found.")
		}
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) adminDeleteArchive(w http.ResponseWriter, r *http.Request) error {
	if _, err := h.requireAdmin(r); err != nil {
		return err
	}
	archiveID := r.PathValue("archive_id")
	err := h.Service.Repo.DeleteArchive(r.Context(), archiveID)
	if err != nil {
		if errors.Is(err, ErrArchiveNotFound) {
			return httpx.NewError(404, "archive_not_found", "Archive not found.")
		}
		return err
	}
	httpx.NoContent(w)
	return nil
}
