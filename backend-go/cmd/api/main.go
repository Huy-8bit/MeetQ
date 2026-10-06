package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"meetq/backend-go/internal/admin"
	"meetq/backend-go/internal/ai"
	"meetq/backend-go/internal/archive"
	"meetq/backend-go/internal/auth"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/livekit"
	"meetq/backend-go/internal/meetings"
	"meetq/backend-go/internal/notify"
	"meetq/backend-go/internal/room"
	"meetq/backend-go/internal/server"
	"meetq/backend-go/internal/store"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	cfg, err := config.Load()
	if err != nil {
		logger.Error("configuration load failed", "error", err.Error())
		os.Exit(1)
	}

	logger.Info("starting MeetQ Go backend", "port", cfg.Port, "env", cfg.DeploymentEnvironment)

	// Redis
	redisOpts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		logger.Error("invalid REDIS_URL", "error", err.Error())
		os.Exit(1)
	}
	redisClient := redis.NewClient(redisOpts)

	// MongoDB
	var mongoClient *mongo.Client
	var mongoDB *mongo.Database
	if cfg.MongoURL != "" {
		mOpts := options.Client().
			ApplyURI(cfg.MongoURL).
			SetMaxPoolSize(cfg.MongoMaxPoolSize).
			SetMinPoolSize(cfg.MongoMinPoolSize).
			SetMaxConnIdleTime(cfg.MongoMaxConnIdleTime).
			SetConnectTimeout(cfg.MongoConnectTimeout).
			SetServerSelectionTimeout(cfg.MongoServerSelectionTimeout)

		mc, err := mongo.Connect(mOpts)
		if err != nil {
			logger.Warn("mongodb connection failed, history will be disabled", "error", err.Error())
		} else {
			mongoClient = mc
			mongoDB = mc.Database(cfg.MongoDatabase)
			logger.Info("connected to mongodb", "database", cfg.MongoDatabase)
		}
	}

	// LiveKit client
	lkClient := livekit.New(cfg.LiveKitWSURLInternal, cfg.LiveKitAPIKey, cfg.LiveKitAPISecret)

	// Python AI client
	aiClient := ai.New(cfg.PythonAIBaseURL, cfg.PythonAIServiceToken, cfg.PythonAITimeout, cfg.PythonAISummaryTimeout)

	// S3 storage
	s3Storage, err := archive.NewStorage(context.Background(), cfg)
	if err != nil {
		logger.Warn("s3 storage setup warning", "error", err.Error())
	}

	// Telegram notifier
	telegramNotifier := &notify.Telegram{
		Enabled:                 cfg.TelegramEnabled,
		NotifyRoomCreated:       cfg.TelegramNotifyRoomCreated,
		NotifyParticipantJoined: cfg.TelegramNotifyParticipantJoined,
		BotToken:                cfg.TelegramBotToken,
		ChatID:                  cfg.TelegramChatID,
		APIBaseURL:              cfg.TelegramAPIBaseURL,
		Timeout:                 cfg.TelegramTimeout,
		Log:                     logger,
	}

	// Repositories
	historyRepo := &history.Repository{
		DB:      mongoDB,
		Timeout: cfg.MongoQueryTimeout,
		Log:     logger,
	}

	archiveRepo := archive.NewRepository(mongoDB, cfg.DefaultMeetingRetentionDays)

	roomStore := store.NewRoomStore(redisClient, time.Duration(cfg.RoomMeetingDurationSeconds)*time.Second)
	accessStore := &room.AccessStore{R: redisClient, TTL: time.Duration(cfg.RoomMeetingDurationSeconds) * time.Second}
	membershipStore := &room.MembershipStore{R: redisClient, TTL: time.Duration(cfg.RoomMeetingDurationSeconds) * time.Second}

	// Session store & auth
	sessionStore := &auth.SessionStore{R: redisClient}
	googleVerifier := auth.NewGoogleVerifier(cfg.GoogleClientID, cfg.GoogleAllowedDomains)
	authService := &auth.Service{
		Cfg:              cfg,
		Sessions:         sessionStore,
		Google:           googleVerifier,
		History:          historyRepo,
		GoogleFailures:   &auth.RateLimiter{R: redisClient, Scope: "google", MaxFailures: 5, Window: 300 * time.Second},
		AdminFailures:    &auth.RateLimiter{R: redisClient, Scope: "admin", MaxFailures: 5, Window: 900 * time.Second},
		FailedLoginDelay: 400 * time.Millisecond,
	}

	// Archive service (implements room.RecordingHooks)
	archiveService := archive.NewService(
		cfg,
		archiveRepo,
		s3Storage,
		lkClient,
		redisClient,
		func(ctx context.Context, eventType, roomID string, payload any) error {
			// publish helper
			envelope := map[string]any{
				"type":    eventType,
				"room_id": roomID,
				"sent_at": time.Now().UTC().Format(time.RFC3339),
				"payload": payload,
			}
			raw, _ := json.Marshal(envelope)
			return redisClient.Publish(ctx, cfg.RedisChannelGatewayControl, raw).Err()
		},
	)

	// Room service
	roomService := &room.Service{
		Cfg:       cfg,
		Store:     roomStore,
		Access:    accessStore,
		Members:   membershipStore,
		History:   historyRepo,
		LiveKit:   lkClient,
		AI:        aiClient,
		Notifier:  telegramNotifier,
		Recording: archiveService,
		Redis:     redisClient,
		Log:       logger,
	}

	// Meetings service (implements archive.MeetingAccessChecker)
	meetingsService := meetings.NewService(mongoDB, archiveRepo)

	// Admin service
	adminService := admin.NewService(cfg, roomStore, redisClient, mongoDB, lkClient, aiClient)

	// HTTP Handlers
	roomHandler := room.NewHandler(roomService, authService, cfg)
	archiveHandler := archive.NewHandler(archiveService, authService, cfg, roomService, meetingsService)
	meetingsHandler := meetings.NewHandler(meetingsService, authService, cfg, archiveRepo)
	adminHandler := admin.NewHandler(adminService, authService, cfg)

	srv := server.NewServer(server.Deps{
		Cfg:      cfg,
		Redis:    redisClient,
		Mongo:    mongoClient,
		DB:       mongoDB,
		Auth:     authService,
		Room:     roomHandler,
		Archive:  archiveHandler,
		Meetings: meetingsHandler,
		Admin:    adminHandler,
		Log:      logger,
	})

	httpServer := &http.Server{
		Addr:              net.JoinHostPort("", cfg.Port),
		Handler:           srv.Handler,
		ReadHeaderTimeout: cfg.HeaderTimeout,
		ReadTimeout:       cfg.ReadTimeout,
		WriteTimeout:      cfg.WriteTimeout,
		IdleTimeout:       cfg.IdleTimeout,
	}

	go func() {
		logger.Info(fmt.Sprintf("listening on http://0.0.0.0:%s", cfg.Port))
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server failed", "error", err.Error())
			os.Exit(1)
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("shutting down server...")

	ctx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()

	if err := httpServer.Shutdown(ctx); err != nil {
		logger.Error("server forced to shutdown", "error", err.Error())
	}

	roomService.StopExpiryTimers()

	if mongoClient != nil {
		_ = mongoClient.Disconnect(ctx)
		logger.Info("closed mongodb connection pool")
	}

	if redisClient != nil {
		_ = redisClient.Close()
		logger.Info("closed redis client")
	}

	logger.Info("MeetQ Go backend exited gracefully")
}
