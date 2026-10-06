package server

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"
	"go.mongodb.org/mongo-driver/v2/mongo"

	"meetq/backend-go/internal/admin"
	"meetq/backend-go/internal/archive"
	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/httpx"
	"meetq/backend-go/internal/meetings"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
	"meetq/backend-go/internal/room"
)

type Server struct {
	Cfg      *config.Config
	Mux      *http.ServeMux
	Handler  http.Handler
	Redis    *redis.Client
	Mongo    *mongo.Client
	Log      *slog.Logger
	Auth     *auth.Service
	Room     *room.Handler
	Archive  *archive.Handler
	Meetings *meetings.Handler
	Admin    *admin.Handler
}

type Deps struct {
	Cfg      *config.Config
	Redis    *redis.Client
	Mongo    *mongo.Client
	DB       *mongo.Database
	Auth     *auth.Service
	Room     *room.Handler
	Archive  *archive.Handler
	Meetings *meetings.Handler
	Admin    *admin.Handler
	Log      *slog.Logger
}

func NewServer(d Deps) *Server {
	mux := http.NewServeMux()
	s := &Server{
		Cfg:      d.Cfg,
		Mux:      mux,
		Redis:    d.Redis,
		Mongo:    d.Mongo,
		Log:      d.Log,
		Auth:     d.Auth,
		Room:     d.Room,
		Archive:  d.Archive,
		Meetings: d.Meetings,
		Admin:    d.Admin,
	}

	s.registerRoutes()
	s.buildMiddlewareChain()
	return s
}

func (s *Server) registerRoutes() {
	// Health & readiness
	s.Mux.HandleFunc("GET /health", s.handleHealth)
	s.Mux.HandleFunc("GET /readiness", s.handleReadiness)
	s.Mux.HandleFunc("GET /api/health", s.handleApiHealth)
	s.Mux.HandleFunc("GET /api/config", s.handleApiConfig)

	// Auth routes
	s.Mux.Handle("POST /api/auth/google", httpx.Handler(s.Auth.GoogleSignIn))
	s.Mux.Handle("GET /api/auth/me", httpx.Handler(s.Auth.Me))
	s.Mux.Handle("POST /api/auth/logout", httpx.Handler(s.Auth.Logout))

	s.Mux.Handle("POST /api/admin/auth/login", httpx.Handler(s.Auth.AdminLogin))
	s.Mux.Handle("GET /api/admin/auth/me", httpx.Handler(s.Auth.AdminMe))
	s.Mux.Handle("POST /api/admin/auth/logout", httpx.Handler(s.Auth.AdminLogout))

	// Domain handlers
	if s.Room != nil {
		s.Room.Register(s.Mux)
	}
	if s.Archive != nil {
		s.Archive.Register(s.Mux)
	}
	if s.Meetings != nil {
		s.Meetings.Register(s.Mux)
	}
	if s.Admin != nil {
		s.Admin.Register(s.Mux)
	}
}

func (s *Server) buildMiddlewareChain() {
	logger := s.Log
	if logger == nil {
		logger = slog.Default()
	}

	handler := http.Handler(s.Mux)
	// Timeout
	handler = httpx.WithTimeout(s.Cfg.WriteTimeout)(handler)
	// CSRF Origin Check
	handler = httpx.OriginCheck(s.Cfg.CORSAllowedOrigins)(handler)
	// CORS
	handler = httpx.CORS(s.Cfg.CORSAllowedOrigins)(handler)
	// Access logging
	handler = httpx.AccessLog(nil)(handler)
	// Request ID propagation
	handler = httpx.RequestID(logger)(handler)
	// Panic recover
	handler = httpx.Recover(handler)

	s.Handler = handler
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]string{
		"status": "ok",
		"time":   platform.NowStr(),
	})
}

func (s *Server) handleReadiness(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()

	redisErr := s.Redis.Ping(ctx).Err()
	var mongoErr error
	if s.Mongo != nil {
		mongoErr = s.Mongo.Ping(ctx, nil)
	}

	if redisErr != nil || mongoErr != nil {
		httpx.JSON(w, http.StatusServiceUnavailable, map[string]any{
			"status": "degraded",
			"redis":  errStr(redisErr),
			"mongo":  errStr(mongoErr),
		})
		return
	}

	httpx.JSON(w, http.StatusOK, map[string]any{
		"status": "ready",
		"time":   platform.NowStr(),
	})
}

func (s *Server) handleApiHealth(w http.ResponseWriter, r *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "gateway-go",
		"time":    platform.NowStr(),
		"dependencies": map[string]string{
			"redis": "ok",
		},
	})
}

func (s *Server) handleApiConfig(w http.ResponseWriter, r *http.Request) {
	httpx.JSON(w, http.StatusOK, map[string]any{
		"room_meeting_duration_seconds": s.Cfg.RoomMeetingDurationSeconds,
		"supported_languages":           models.SupportedLanguages,
		"recording_available":           s.Cfg.MeetingRecordingEnabled,
		"meeting_history_available":     s.Cfg.MongoURL != "",
	})
}

func errStr(err error) string {
	if err == nil {
		return "ok"
	}
	return fmt.Sprintf("error: %v", err)
}
