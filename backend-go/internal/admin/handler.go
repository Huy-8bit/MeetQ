package admin

import (
	"errors"
	"net/http"
	"time"

	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/httpx"
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
	mux.Handle("GET /api/admin/health", httpx.Handler(h.getHealth))
	mux.Handle("GET /api/admin/overview", httpx.Handler(h.getOverview))
	mux.Handle("GET /api/admin/rooms", httpx.Handler(h.listRooms))
	mux.Handle("GET /api/admin/rooms/{room_id}", httpx.Handler(h.getRoom))
	mux.Handle("GET /api/admin/rooms/{room_id}/timeline", httpx.Handler(h.getRoomTimeline))
	mux.Handle("GET /api/admin/rooms/{room_id}/transcript", httpx.Handler(h.getRoomTranscript))
	mux.Handle("GET /api/admin/meetings", httpx.Handler(h.listMeetings))
	mux.Handle("GET /api/admin/meetings/{room_id}", httpx.Handler(h.getMeeting))
	mux.Handle("GET /api/admin/meetings/{room_id}/transcripts", httpx.Handler(h.getMeetingTranscripts))
	mux.Handle("GET /api/admin/meetings/{room_id}/relays", httpx.Handler(h.getMeetingRelays))
	mux.Handle("GET /api/admin/meetings/{room_id}/chat", httpx.Handler(h.getMeetingChat))
	mux.Handle("GET /api/admin/meetings/{room_id}/summaries", httpx.Handler(h.getMeetingSummaries))
	mux.Handle("POST /api/admin/meetings/{room_id}/summaries/final", httpx.Handler(h.regenerateFinalSummary))
	mux.Handle("GET /api/admin/meetings/{room_id}/participants", httpx.Handler(h.getMeetingParticipants))
	mux.Handle("GET /api/admin/ai/metrics", httpx.Handler(h.getAiMetrics))
	mux.Handle("GET /api/admin/issues", httpx.Handler(h.getIssues))
	mux.Handle("GET /api/admin/issues/{code}", httpx.Handler(h.getIssueDetail))
	mux.Handle("GET /api/admin/analytics", httpx.Handler(h.getAnalytics))
	mux.Handle("GET /api/admin/config", httpx.Handler(h.getConfig))
}

func (h *Handler) requireAdmin(r *http.Request) error {
	_, err := h.Auth.RequireAdmin(r)
	return err
}

func (h *Handler) getHealth(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, h.Service.SystemHealth(r.Context()))
	return nil
}

func (h *Handler) getConfig(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, h.Service.GetConfig(r.Context()))
	return nil
}

func (h *Handler) getOverview(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	todayStartStr := r.URL.Query().Get("today_start")
	var todayStart *time.Time
	if todayStartStr != "" {
		t := platform.ParseTime(todayStartStr)
		if t == nil {
			return httpx.NewError(422, "invalid_request", "today_start must be an ISO-8601 datetime.")
		}
		todayStart = t
	}
	res, err := h.Service.GetOverview(r.Context(), todayStart)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) listRooms(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(q, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 25, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}

	var qPtr, statusPtr, aiModePtr, langPtr *string
	if s, ok := httpx.QueryString(q, "q"); ok && s != "" {
		qPtr = &s
	}
	if s, ok := httpx.QueryString(q, "status"); ok && s != "" {
		statusPtr = &s
	}
	if s, ok := httpx.QueryString(q, "ai_mode"); ok && s != "" {
		aiModePtr = &s
	}
	if s, ok := httpx.QueryString(q, "language"); ok && s != "" {
		langPtr = &s
	}

	res, err := h.Service.ListLiveRooms(r.Context(), qPtr, statusPtr, aiModePtr, langPtr, page, pageSize)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getRoom(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	res, err := h.Service.GetLiveRoom(r.Context(), roomID)
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found.")
		}
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getRoomTimeline(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	limit := httpx.QueryInt{Name: "limit", Default: 50, Min: httpx.Ptr(1), Max: httpx.Ptr(150)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}
	res, err := h.Service.GetRoomTimeline(r.Context(), roomID, limit)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getRoomTranscript(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	limit := httpx.QueryInt{Name: "limit", Default: 100, Min: httpx.Ptr(1), Max: httpx.Ptr(200)}.Parse(q, errs)
	kind, _ := httpx.QueryString(q, "kind")
	if kind == "" {
		kind = "all"
	}
	if !errs.Empty() {
		return errs
	}
	res, err := h.Service.GetRoomTranscript(r.Context(), roomID, kind, limit)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) listMeetings(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(q, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 25, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}

	var qPtr, fromPtr, toPtr, langPtr, aiModePtr, sumStatusPtr, statusPtr *string
	if s, ok := httpx.QueryString(q, "q"); ok && s != "" {
		qPtr = &s
	}
	if s, ok := httpx.QueryString(q, "from"); ok && s != "" {
		fromPtr = &s
	}
	if s, ok := httpx.QueryString(q, "to"); ok && s != "" {
		toPtr = &s
	}
	if s, ok := httpx.QueryString(q, "language"); ok && s != "" {
		langPtr = &s
	}
	if s, ok := httpx.QueryString(q, "ai_mode"); ok && s != "" {
		aiModePtr = &s
	}
	if s, ok := httpx.QueryString(q, "summary_status"); ok && s != "" {
		sumStatusPtr = &s
	}
	if s, ok := httpx.QueryString(q, "status"); ok && s != "" {
		statusPtr = &s
	}

	res, err := h.Service.ListMeetings(r.Context(), qPtr, fromPtr, toPtr, langPtr, aiModePtr, sumStatusPtr, statusPtr, page, pageSize)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeeting(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	res, err := h.Service.GetMeetingDetail(r.Context(), roomID)
	if err != nil {
		if errors.Is(err, ErrRoomNotFound) {
			return httpx.NewError(404, "room_not_found", "Room not found.")
		}
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeetingTranscripts(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(q, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 50, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}
	res, err := h.Service.GetMeetingTranscripts(r.Context(), roomID, page, pageSize)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeetingRelays(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(q, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 50, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}
	res, err := h.Service.GetMeetingRelays(r.Context(), roomID, page, pageSize)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeetingChat(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(q, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 50, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}
	res, err := h.Service.GetMeetingChat(r.Context(), roomID, page, pageSize)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeetingSummaries(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	res, err := h.Service.GetMeetingSummaries(r.Context(), roomID)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) regenerateFinalSummary(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	body, _, _ := httpx.DecodeJSON(r, 64<<10)
	var langPtr *string
	if body != nil {
		if l, ok, _ := httpx.BodyString(body, "language"); ok && l != "" {
			langPtr = &l
		}
	}
	res, err := h.Service.RegenerateFinalSummary(r.Context(), roomID, langPtr)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeetingParticipants(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	res, err := h.Service.GetMeetingParticipants(r.Context(), roomID)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getAiMetrics(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	window := r.URL.Query().Get("window")
	if window == "" {
		window = "1h"
	}
	res, err := h.Service.GetAiMetrics(r.Context(), window)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getIssues(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	window := r.URL.Query().Get("window")
	if window == "" {
		window = "24h"
	}
	includeInfo := r.URL.Query().Get("include_info") == "true"
	res, err := h.Service.GetIssues(r.Context(), window, includeInfo)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getIssueDetail(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	code := r.PathValue("code")
	window := r.URL.Query().Get("window")
	if window == "" {
		window = "24h"
	}
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(q, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 25, Min: httpx.Ptr(1), Max: httpx.Ptr(100)}.Parse(q, errs)
	if !errs.Empty() {
		return errs
	}
	res, err := h.Service.GetIssueDetail(r.Context(), code, window, page, pageSize)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getAnalytics(w http.ResponseWriter, r *http.Request) error {
	if err := h.requireAdmin(r); err != nil {
		return err
	}
	q := r.URL.Query()
	fromStr := q.Get("from")
	toStr := q.Get("to")
	start := platform.ParseTime(fromStr)
	end := platform.ParseTime(toStr)
	if start == nil || end == nil || !end.After(*start) {
		return httpx.NewError(422, "invalid_request", "from must be before to.")
	}
	if end.Sub(*start) > 366*24*time.Hour {
		return httpx.NewError(422, "invalid_request", "Range cannot exceed 366 days.")
	}
	res, err := h.Service.GetAnalytics(r.Context(), *start, *end, 0)
	if err != nil {
		return err
	}
	httpx.JSON(w, http.StatusOK, res)
	return nil
}
