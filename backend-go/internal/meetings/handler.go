package meetings

import (
	"errors"
	"net/http"

	"meetq/backend-go/internal/archive"
	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/httpx"
)

type Handler struct {
	Service     *Service
	Auth        *auth.Service
	Cfg         *config.Config
	ArchiveRepo *archive.Repository
}

func NewHandler(s *Service, a *auth.Service, cfg *config.Config, ar *archive.Repository) *Handler {
	return &Handler{
		Service:     s,
		Auth:        a,
		Cfg:         cfg,
		ArchiveRepo: ar,
	}
}

func (h *Handler) Register(mux *http.ServeMux) {
	mux.Handle("GET /api/meetings", httpx.Handler(h.listMeetings))
	mux.Handle("GET /api/meetings/search", httpx.Handler(h.searchMeetings))
	mux.Handle("GET /api/meetings/{room_id}", httpx.Handler(h.getMeeting))
	mux.Handle("GET /api/meetings/{room_id}/transcript", httpx.Handler(h.getTranscript))
	mux.Handle("GET /api/meetings/{room_id}/relay", httpx.Handler(h.getRelay))
	mux.Handle("GET /api/meetings/{room_id}/chat", httpx.Handler(h.getChat))
	mux.Handle("GET /api/meetings/{room_id}/summary", httpx.Handler(h.getSummary))
	mux.Handle("GET /api/meetings/{room_id}/participants", httpx.Handler(h.getParticipants))
	mux.Handle("GET /api/meetings/{room_id}/recordings", httpx.Handler(h.getRecordings))
	mux.Handle("GET /api/meetings/{room_id}/search", httpx.Handler(h.searchMeeting))
	mux.Handle("GET /api/meetings/{room_id}/messages", httpx.Handler(h.getMessages))
}

func (h *Handler) requireUser(r *http.Request) (string, error) {
	session, err := h.Auth.CurrentUser(r)
	if err != nil {
		return "", err
	}
	return auth.UserID(session), nil
}

func (h *Handler) mapAccessError(err error) error {
	if errors.Is(err, ErrMeetingNotFound) {
		return httpx.NewError(404, "meeting_not_found", "Meeting not found.")
	}
	if errors.Is(err, ErrMeetingDeleted) {
		return httpx.NewError(410, "meeting_archive_deleted", "This meeting's recording and content have been deleted.")
	}
	if errors.Is(err, ErrMeetingExpired) {
		return httpx.NewError(410, "meeting_archive_expired", "This meeting's retention period has ended.")
	}
	return err
}

func (h *Handler) listMeetings(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}

	query := r.URL.Query()
	errs := &httpx.ValidationError{}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(query, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 20, Min: httpx.Ptr(1), Max: httpx.Ptr(50)}.Parse(query, errs)
	filter, _ := httpx.QueryString(query, "filter")
	if filter == "" {
		filter = "all"
	}
	if filter != "all" && filter != "created" && filter != "recorded" && filter != "summary" {
		return httpx.NewError(422, "invalid_filter", "Unknown filter.")
	}
	dateRange, _ := httpx.QueryString(query, "range")
	if dateRange == "" {
		dateRange = "all"
	}
	if dateRange != "all" && dateRange != "today" && dateRange != "7d" && dateRange != "30d" {
		return httpx.NewError(422, "invalid_filter", "Unknown filter.")
	}
	q, _ := httpx.QueryString(query, "q")
	if !errs.Empty() {
		return errs
	}

	var qPtr *string
	if q != "" {
		normQ, err := NormalizeQuery(q)
		if err != nil {
			return httpx.NewError(422, "invalid_search_query", err.Error())
		}
		qPtr = &normQ
	}

	res, err := h.Service.ListMeetings(r.Context(), userID, page, pageSize, qPtr, filter, dateRange)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) searchMeetings(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}

	query := r.URL.Query()
	errs := &httpx.ValidationError{}
	q, ok := httpx.QueryString(query, "q")
	if !ok || q == "" {
		errs.Add([]any{"query", "q"}, "missing", "Field required")
	}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(query, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 20, Min: httpx.Ptr(1), Max: httpx.Ptr(50)}.Parse(query, errs)
	if !errs.Empty() {
		return errs
	}

	normQ, err := NormalizeQuery(q)
	if err != nil {
		return httpx.NewError(422, "invalid_search_query", err.Error())
	}

	res, err := h.Service.SearchAll(r.Context(), userID, normQ, page, pageSize)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMeeting(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	detail, err := h.Service.Detail(r.Context(), access)
	if err != nil {
		return err
	}

	// format recordings to public format
	if recs, ok := detail["recordings"].([]map[string]any); ok {
		pubRecs := make([]map[string]any, 0, len(recs))
		for _, rc := range recs {
			pr := archive.PublicRecording(rc)
			pr["playable"] = rc["status"] == archive.RecReady
			pubRecs = append(pubRecs, pr)
		}
		detail["recordings"] = pubRecs
	}

	httpx.JSON(w, http.StatusOK, detail)
	return nil
}

func (h *Handler) contentParams(r *http.Request) (*string, *string, *string, int, error) {
	q := r.URL.Query()
	errs := &httpx.ValidationError{}
	limit := httpx.QueryInt{Name: "limit", Default: ContentPageSize, Min: httpx.Ptr(1), Max: httpx.Ptr(ContentPageSizeMax)}.Parse(q, errs)
	if !errs.Empty() {
		return nil, nil, nil, 0, errs
	}
	var cursor, before, start *string
	if c, ok := httpx.QueryString(q, "cursor"); ok && c != "" {
		cursor = &c
	}
	if b, ok := httpx.QueryString(q, "before"); ok && b != "" {
		before = &b
	}
	if s, ok := httpx.QueryString(q, "start"); ok && s != "" {
		start = &s
	}
	return cursor, before, start, limit, nil
}

func (h *Handler) getTranscript(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	cursor, before, start, limit, err := h.contentParams(r)
	if err != nil {
		return err
	}

	res, err := h.Service.Transcript(r.Context(), access, cursor, before, start, limit)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getRelay(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	cursor, before, start, limit, err := h.contentParams(r)
	if err != nil {
		return err
	}

	res, err := h.Service.Relay(r.Context(), access, cursor, before, start, limit)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getChat(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	cursor, before, start, limit, err := h.contentParams(r)
	if err != nil {
		return err
	}

	res, err := h.Service.Chat(r.Context(), access, cursor, before, start, limit)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getSummary(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	detail, err := h.Service.Detail(r.Context(), access)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"summary": detail["summary"]})
	return nil
}

func (h *Handler) getParticipants(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	parts, err := h.Service.Participants(r.Context(), access)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"items": parts})
	return nil
}

func (h *Handler) getRecordings(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	_, err = h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	recs := []map[string]any{}
	if h.ArchiveRepo != nil && h.ArchiveRepo.Enabled() {
		raw, _ := h.ArchiveRepo.ListRecordings(r.Context(), roomID)
		if raw != nil {
			for _, rc := range raw {
				pr := archive.PublicRecording(rc)
				pr["playable"] = rc["status"] == archive.RecReady
				recs = append(recs, pr)
			}
		}
	}

	httpx.JSON(w, http.StatusOK, map[string]any{"items": recs})
	return nil
}

func (h *Handler) searchMeeting(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	query := r.URL.Query()
	errs := &httpx.ValidationError{}
	q, ok := httpx.QueryString(query, "q")
	if !ok || q == "" {
		errs.Add([]any{"query", "q"}, "missing", "Field required")
	}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(query, errs)
	pageSize := httpx.QueryInt{Name: "page_size", Default: 20, Min: httpx.Ptr(1), Max: httpx.Ptr(50)}.Parse(query, errs)
	if !errs.Empty() {
		return errs
	}

	normQ, err := NormalizeQuery(q)
	if err != nil {
		return httpx.NewError(422, "invalid_search_query", err.Error())
	}

	res, err := h.Service.SearchMeeting(r.Context(), access, normQ, page, pageSize)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}

func (h *Handler) getMessages(w http.ResponseWriter, r *http.Request) error {
	userID, err := h.requireUser(r)
	if err != nil {
		return err
	}
	roomID := r.PathValue("room_id")
	access, err := h.Service.Access(r.Context(), roomID, userID)
	if err != nil {
		return h.mapAccessError(err)
	}

	query := r.URL.Query()
	errs := &httpx.ValidationError{}
	kind, _ := httpx.QueryString(query, "kind")
	if kind == "" {
		kind = "transcript"
	}
	if kind != "transcript" && kind != "relay" && kind != "chat" {
		errs.Add([]any{"query", "kind"}, "value_error", "kind must be transcript, relay or chat")
	}
	page := httpx.QueryInt{Name: "page", Default: 1, Min: httpx.Ptr(1)}.Parse(query, errs)
	if !errs.Empty() {
		return errs
	}

	res, err := h.Service.Messages(r.Context(), access, kind, page)
	if err != nil {
		return err
	}

	httpx.JSON(w, http.StatusOK, res)
	return nil
}
