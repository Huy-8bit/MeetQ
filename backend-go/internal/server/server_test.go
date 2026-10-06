package server_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"meetq/backend-go/internal/admin"
	"meetq/backend-go/internal/archive"
	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/livekit"
	"meetq/backend-go/internal/meetings"
	"meetq/backend-go/internal/room"
	"meetq/backend-go/internal/server"
	"meetq/backend-go/internal/store"
)

func setupTestServer(t *testing.T) (*server.Server, *miniredis.Miniredis) {
	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("failed to start miniredis: %v", err)
	}

	redisClient := redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})

	cfg := &config.Config{
		Port:                        "8080",
		RoomJWTSecret:               "test-jwt-secret-very-long-enough-32bytes",
		RoomMeetingDurationSeconds:  3600,
		RoomTokenTTLSeconds:         86400,
		UserAuthRequired:            false, // local dev test allows anonymous room creation/join
		AdminUsername:               "admin",
		AdminPassword:               "admin123456",
		AdminSessionTTLSeconds:      3600,
		DefaultMeetingRetentionDays: 7,
		CORSAllowedOrigins:          []string{"http://localhost:3000"},
	}

	sessionStore := &auth.SessionStore{R: redisClient}
	authService := &auth.Service{
		Cfg:            cfg,
		Sessions:       sessionStore,
		GoogleFailures: &auth.RateLimiter{R: redisClient, Scope: "google", MaxFailures: 5, Window: time.Minute},
		AdminFailures:  &auth.RateLimiter{R: redisClient, Scope: "admin", MaxFailures: 5, Window: time.Minute},
	}

	roomStore := store.NewRoomStore(redisClient, time.Hour)
	accessStore := &room.AccessStore{R: redisClient, TTL: time.Hour}
	membershipStore := &room.MembershipStore{R: redisClient, TTL: time.Hour}

	archiveRepo := archive.NewRepository(nil, 7)
	archiveService := archive.NewService(cfg, archiveRepo, nil, nil, redisClient, nil)

	lkClient := livekit.New("ws://localhost:7880", "devkey", "devkeysecretdevkeysecretdevkey12")

	roomService := &room.Service{
		Cfg:       cfg,
		Store:     roomStore,
		Access:    accessStore,
		Members:   membershipStore,
		Redis:     redisClient,
		LiveKit:   lkClient,
		Recording: archiveService,
	}

	meetingsService := meetings.NewService(nil, archiveRepo)
	adminService := admin.NewService(cfg, roomStore, redisClient, nil, nil, nil)

	roomHandler := room.NewHandler(roomService, authService, cfg)
	archiveHandler := archive.NewHandler(archiveService, authService, cfg, roomService, meetingsService)
	meetingsHandler := meetings.NewHandler(meetingsService, authService, cfg, archiveRepo)
	adminHandler := admin.NewHandler(adminService, authService, cfg)

	srv := server.NewServer(server.Deps{
		Cfg:      cfg,
		Redis:    redisClient,
		Auth:     authService,
		Room:     roomHandler,
		Archive:  archiveHandler,
		Meetings: meetingsHandler,
		Admin:    adminHandler,
	})

	return srv, mr
}

func TestHealthEndpoints(t *testing.T) {
	srv, mr := setupTestServer(t)
	defer mr.Close()

	// GET /health
	req := httptest.NewRequest("GET", "/health", nil)
	w := httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	// GET /readiness
	req = httptest.NewRequest("GET", "/readiness", nil)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	// GET /api/config
	req = httptest.NewRequest("GET", "/api/config", nil)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
	var conf map[string]any
	json.NewDecoder(w.Body).Decode(&conf)
	if conf["room_meeting_duration_seconds"] == nil {
		t.Fatalf("expected room_meeting_duration_seconds in config")
	}
}

func TestRoomLifecycle(t *testing.T) {
	srv, mr := setupTestServer(t)
	defer mr.Close()

	// 1. Create Room
	body := []byte(`{"title":"Sprint Review","room_languages":["en","vi"]}`)
	req := httptest.NewRequest("POST", "/api/rooms", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("create room expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var createResp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &createResp); err != nil {
		t.Fatalf("failed to decode create room response: %v", err)
	}
	roomObj, _ := createResp["room"].(map[string]any)
	roomID, _ := roomObj["room_id"].(string)
	if roomID == "" {
		t.Fatalf("expected non-empty room_id")
	}

	// 2. Get Room
	req = httptest.NewRequest("GET", "/api/rooms/"+roomID, nil)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("get room expected 200, got %d", w.Code)
	}

	// 3. Join Room
	joinBody := []byte(`{"display_name":"Alice","language":"en"}`)
	req = httptest.NewRequest("POST", "/api/rooms/"+roomID+"/join", bytes.NewReader(joinBody))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("join room expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var joinResp map[string]any
	json.Unmarshal(w.Body.Bytes(), &joinResp)
	tokenObj, _ := joinResp["room_token"].(map[string]any)
	roomToken, _ := tokenObj["token"].(string)
	if roomToken == "" {
		t.Fatalf("expected non-empty room token")
	}

	// 4. Check Permissions with Token
	req = httptest.NewRequest("GET", "/api/rooms/"+roomID+"/permissions", nil)
	req.Header.Set("Authorization", "Bearer "+roomToken)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("permissions expected 200, got %d: %s", w.Code, w.Body.String())
	}

	// 5. Leave Room
	req = httptest.NewRequest("DELETE", "/api/rooms/"+roomID+"/leave", nil)
	req.Header.Set("Authorization", "Bearer "+roomToken)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent {
		t.Fatalf("leave room expected 204, got %d", w.Code)
	}
}

func TestAdminAuthAndOverview(t *testing.T) {
	srv, mr := setupTestServer(t)
	defer mr.Close()

	// 1. Admin login with correct password
	loginBody := []byte(`{"username":"admin","password":"admin123456"}`)
	req := httptest.NewRequest("POST", "/api/admin/auth/login", bytes.NewReader(loginBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("admin login expected 200, got %d: %s", w.Code, w.Body.String())
	}

	cookies := w.Result().Cookies()
	var adminCookie *http.Cookie
	for _, c := range cookies {
		if c.Name == auth.AdminCookie {
			adminCookie = c
			break
		}
	}
	if adminCookie == nil {
		t.Fatalf("expected admin cookie to be set")
	}

	// 2. Admin Get Overview
	req = httptest.NewRequest("GET", "/api/admin/overview", nil)
	req.AddCookie(adminCookie)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("admin overview expected 200, got %d: %s", w.Code, w.Body.String())
	}

	// 3. Admin Get Config
	req = httptest.NewRequest("GET", "/api/admin/config", nil)
	req.AddCookie(adminCookie)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("admin config expected 200, got %d: %s", w.Code, w.Body.String())
	}

	// 4. Admin Logout
	req = httptest.NewRequest("POST", "/api/admin/auth/logout", nil)
	req.AddCookie(adminCookie)
	w = httptest.NewRecorder()
	srv.Handler.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent {
		t.Fatalf("admin logout expected 204, got %d", w.Code)
	}
}
