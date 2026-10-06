// Package config reads the environment. Variable names are the same as the Python
// gateway (BE/server/config.py) so both services can share one .env during the
// migration; Go-only settings are prefixed GO_ or PYTHON_AI_.
package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	// Go service
	Port            string
	LogLevel        string
	ShutdownTimeout time.Duration
	ReadTimeout     time.Duration
	WriteTimeout    time.Duration
	IdleTimeout     time.Duration
	HeaderTimeout   time.Duration
	// Background jobs (recording reconcile, archive finalize, cleanup). They share
	// Redis leases with the Python workers, so both may run; off by default.
	WorkersEnabled bool
	// Room expiry: persist "expired" + ask Python for the final summary.
	ExpirySchedulerEnabled bool

	// Python AI service (internal API)
	PythonAIBaseURL        string
	PythonAIServiceToken   string
	PythonAITimeout        time.Duration
	PythonAISummaryTimeout time.Duration

	// Redis
	RedisURL                      string
	RedisChannelGatewayControl    string
	RedisChannelInterpreterEvents string

	// MongoDB
	MongoURL                    string
	MongoDatabase               string
	MongoMaxPoolSize            uint64
	MongoMinPoolSize            uint64
	MongoMaxConnIdleTime        time.Duration
	MongoServerSelectionTimeout time.Duration
	MongoConnectTimeout         time.Duration
	MongoQueryTimeout           time.Duration

	// Rooms / tokens
	RoomJWTSecret              string
	RoomTokenTTLSeconds        int
	RoomMeetingDurationSeconds int
	RoomMaxParticipants        int

	// LiveKit
	LiveKitAPIKey         string
	LiveKitAPISecret      string
	LiveKitWSURLPublic    string
	LiveKitWSURLInternal  string
	PublicAppURL          string
	PublicGatewayURL      string
	PublicGatewayWSURL    string
	WSStaleTimeoutSeconds int
	WSStaleSweepSeconds   int

	// Telegram
	TelegramEnabled                 bool
	TelegramNotifyRoomCreated       bool
	TelegramNotifyParticipantJoined bool
	TelegramBotToken                string
	TelegramChatID                  string
	TelegramAPIBaseURL              string
	TelegramTimeout                 time.Duration

	// Auth
	AdminUsername          string
	AdminPasswordHash      string
	AdminPassword          string
	AdminSessionTTLSeconds int
	GoogleClientID         string
	GoogleAllowedDomains   string
	UserSessionTTLSeconds  int
	UserAuthRequired       bool
	AuthCookieSecure       bool
	CORSAllowedOrigins     []string

	// Read-only display values (admin config page)
	OpenAIRealtimeModel              string
	OpenAIRealtimeTranscriptionModel string
	OpenAISummaryModel               string
	MeetingSummaryLanguage           string
	MeetingSummaryMaxSourceItems     int
	LiveKitLineIsolationEnabled      bool
	OpsEventRetentionDays            int

	// Archive / recording
	MeetingArchiveBucket        string
	MeetingArchivePrefix        string
	AWSRegion                   string
	S3EndpointURL               string
	S3PublicEndpointURL         string
	S3ForcePathStyle            bool
	S3ServerSideEncryption      string
	S3Timeout                   time.Duration
	DefaultMeetingRetentionDays int
	MeetingRecordingEnabled     bool
	RecordingLayout             string
	RecordingURLTTLSeconds      int
	RecordingPollInterval       time.Duration
	ArchivePollInterval         time.Duration
	ArchiveCleanupInterval      time.Duration
	ArchiveSummaryWaitSeconds   int
	DeploymentEnvironment       string
}

func Load() (*Config, error) {
	c := &Config{
		Port:                   env("GO_API_PORT", "8080"),
		LogLevel:               env("LOG_LEVEL", "INFO"),
		ShutdownTimeout:        durationSeconds("GO_SHUTDOWN_TIMEOUT_SECONDS", 25),
		ReadTimeout:            durationSeconds("GO_HTTP_READ_TIMEOUT_SECONDS", 30),
		WriteTimeout:           durationSeconds("GO_HTTP_WRITE_TIMEOUT_SECONDS", 120),
		IdleTimeout:            durationSeconds("GO_HTTP_IDLE_TIMEOUT_SECONDS", 120),
		HeaderTimeout:          durationSeconds("GO_HTTP_HEADER_TIMEOUT_SECONDS", 10),
		WorkersEnabled:         boolean("GO_WORKERS_ENABLED", false),
		ExpirySchedulerEnabled: boolean("GO_EXPIRY_SCHEDULER_ENABLED", true),

		PythonAIBaseURL:        strings.TrimRight(env("PYTHON_AI_BASE_URL", "http://localhost:8000"), "/"),
		PythonAIServiceToken:   env("PYTHON_AI_SERVICE_TOKEN", ""),
		PythonAITimeout:        durationSeconds("PYTHON_AI_TIMEOUT_SECONDS", 15),
		PythonAISummaryTimeout: durationSeconds("PYTHON_AI_SUMMARY_TIMEOUT_SECONDS", 120),

		RedisURL:                      env("REDIS_URL", "redis://localhost:6379"),
		RedisChannelGatewayControl:    env("REDIS_CHANNEL_GATEWAY_CONTROL", "brseai:v1:gateway:control"),
		RedisChannelInterpreterEvents: env("REDIS_CHANNEL_INTERPRETER_EVENTS", "brseai:v1:interpreter:events"),

		MongoDatabase:               env("MONGODB_DATABASE", "brseai"),
		MongoMaxPoolSize:            uint64(integer("GO_MONGODB_MAX_POOL_SIZE", 20)),
		MongoMinPoolSize:            uint64(integer("GO_MONGODB_MIN_POOL_SIZE", 0)),
		MongoMaxConnIdleTime:        durationSeconds("GO_MONGODB_MAX_CONN_IDLE_SECONDS", 300),
		MongoServerSelectionTimeout: durationMillis("MONGODB_SERVER_SELECTION_TIMEOUT_MS", 500),
		MongoConnectTimeout:         durationMillis("MONGODB_CONNECT_TIMEOUT_MS", 500),
		MongoQueryTimeout:           durationSeconds("GO_MONGODB_QUERY_TIMEOUT_SECONDS", 15),

		RoomJWTSecret:              env("ROOM_JWT_SECRET", ""),
		RoomTokenTTLSeconds:        integer("ROOM_TOKEN_TTL_SECONDS", 86400),
		RoomMeetingDurationSeconds: integer("ROOM_MEETING_DURATION_SECONDS", 3600),
		RoomMaxParticipants:        integer("ROOM_MAX_PARTICIPANTS", 0),

		LiveKitAPIKey:         env("LIVEKIT_API_KEY", ""),
		LiveKitAPISecret:      env("LIVEKIT_API_SECRET", ""),
		LiveKitWSURLPublic:    env("LIVEKIT_WS_URL_PUBLIC", "ws://localhost:7880"),
		LiveKitWSURLInternal:  env("LIVEKIT_WS_URL_INTERNAL", "ws://localhost:7880"),
		PublicAppURL:          env("PUBLIC_APP_URL", "http://localhost:3000"),
		PublicGatewayURL:      env("PUBLIC_GATEWAY_URL", "http://localhost:8000"),
		PublicGatewayWSURL:    env("PUBLIC_GATEWAY_WS_URL", ""),
		WSStaleTimeoutSeconds: integer("WS_STALE_TIMEOUT_SECONDS", 90),
		WSStaleSweepSeconds:   integer("WS_STALE_SWEEP_INTERVAL_SECONDS", 15),

		TelegramEnabled:                 boolean("TELEGRAM_NOTIFICATIONS_ENABLED", false),
		TelegramNotifyRoomCreated:       boolean("TELEGRAM_NOTIFY_ROOM_CREATED", true),
		TelegramNotifyParticipantJoined: boolean("TELEGRAM_NOTIFY_PARTICIPANT_JOINED", true),
		TelegramBotToken:                strings.TrimSpace(env("TELEGRAM_BOT_TOKEN", "")),
		TelegramChatID:                  strings.TrimSpace(env("TELEGRAM_CHAT_ID", "")),
		TelegramAPIBaseURL:              strings.TrimRight(env("TELEGRAM_API_BASE_URL", "https://api.telegram.org"), "/"),
		TelegramTimeout:                 durationFloatSeconds("TELEGRAM_REQUEST_TIMEOUT_SECONDS", 3.0, 0.5),

		AdminUsername:          env("ADMIN_USERNAME", ""),
		AdminPasswordHash:      env("ADMIN_PASSWORD_HASH", ""),
		AdminPassword:          env("ADMIN_PASSWORD", ""),
		AdminSessionTTLSeconds: integer("ADMIN_SESSION_TTL_SECONDS", 43200),
		GoogleClientID:         env("GOOGLE_CLIENT_ID", ""),
		GoogleAllowedDomains:   env("GOOGLE_ALLOWED_DOMAINS", ""),
		UserSessionTTLSeconds:  integer("USER_SESSION_TTL_SECONDS", 1209600),
		UserAuthRequired:       boolean("USER_AUTH_REQUIRED", true),
		AuthCookieSecure:       boolean("AUTH_COOKIE_SECURE", true),
		CORSAllowedOrigins:     corsOrigins(os.Getenv("CORS_ALLOWED_ORIGINS")),

		OpenAIRealtimeModel:              env("OPENAI_REALTIME_MODEL", "gpt-realtime"),
		OpenAIRealtimeTranscriptionModel: env("OPENAI_REALTIME_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"),
		OpenAISummaryModel:               env("OPENAI_SUMMARY_MODEL", "gpt-4o-mini"),
		MeetingSummaryLanguage:           env("MEETING_SUMMARY_LANGUAGE", "en"),
		MeetingSummaryMaxSourceItems:     integer("MEETING_SUMMARY_MAX_SOURCE_ITEMS", 240),
		LiveKitLineIsolationEnabled:      boolean("LIVEKIT_LINE_ISOLATION_ENABLED", true),
		OpsEventRetentionDays:            integer("OPS_EVENT_RETENTION_DAYS", 30),

		MeetingArchiveBucket:        strings.TrimSpace(env("MEETING_ARCHIVE_BUCKET", "")),
		MeetingArchivePrefix:        env("MEETING_ARCHIVE_PREFIX", "meetings"),
		AWSRegion:                   env("AWS_REGION", ""),
		S3EndpointURL:               env("S3_ENDPOINT_URL", ""),
		S3PublicEndpointURL:         env("S3_PUBLIC_ENDPOINT_URL", ""),
		S3ForcePathStyle:            boolean("S3_FORCE_PATH_STYLE", false),
		S3ServerSideEncryption:      envAllowEmpty("S3_SERVER_SIDE_ENCRYPTION", "AES256"),
		S3Timeout:                   durationSeconds("GO_S3_TIMEOUT_SECONDS", 30),
		DefaultMeetingRetentionDays: integer("DEFAULT_MEETING_RETENTION_DAYS", 7),
		MeetingRecordingEnabled:     boolean("MEETING_RECORDING_ENABLED", true),
		RecordingLayout:             env("RECORDING_LAYOUT", "speaker"),
		RecordingURLTTLSeconds:      integer("RECORDING_URL_TTL_SECONDS", 600),
		RecordingPollInterval:       durationFloatSeconds("RECORDING_POLL_INTERVAL_SECONDS", 3.0, 0.5),
		ArchivePollInterval:         durationFloatSeconds("ARCHIVE_POLL_INTERVAL_SECONDS", 20.0, 1),
		ArchiveCleanupInterval:      durationFloatSeconds("ARCHIVE_CLEANUP_INTERVAL_SECONDS", 3600.0, 1),
		ArchiveSummaryWaitSeconds:   integer("ARCHIVE_SUMMARY_WAIT_SECONDS", 300),
		DeploymentEnvironment:       env("DEPLOYMENT_ENVIRONMENT", "local"),
	}
	mongoURL, err := effectiveMongoURL(c.MongoDatabase)
	if err != nil {
		return nil, err
	}
	c.MongoURL = mongoURL
	if c.RoomJWTSecret == "" {
		return nil, fmt.Errorf("ROOM_JWT_SECRET is required")
	}
	if c.LiveKitAPIKey == "" || c.LiveKitAPISecret == "" {
		return nil, fmt.Errorf("LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required")
	}
	return c, nil
}

// AdminEnabled mirrors server.service.auth.dependencies.admin_enabled.
func (c *Config) AdminEnabled() bool {
	secret := strings.TrimSpace(c.AdminPasswordHash)
	if secret == "" {
		secret = strings.TrimSpace(c.AdminPassword)
	}
	return strings.TrimSpace(c.AdminUsername) != "" && secret != ""
}

func (c *Config) StorageConfigured() bool { return c.MeetingArchiveBucket != "" }

// effectiveMongoURL mirrors server.integrations.mongodb._effective_mongodb_url:
// history is disabled (empty URL) unless credentials are available.
func effectiveMongoURL(database string) (string, error) {
	explicit := strings.TrimSpace(os.Getenv("MONGODB_URL"))
	username := os.Getenv("MONGODB_USERNAME")
	password := os.Getenv("MONGODB_PASSWORD")
	authSource := os.Getenv("MONGODB_AUTH_SOURCE")
	if authSource == "" {
		authSource = database
	}
	if explicit != "" {
		parsed, err := url.Parse(explicit)
		if err != nil {
			return "", fmt.Errorf("MONGODB_URL is invalid")
		}
		if parsed.User != nil {
			if _, ok := parsed.User.Password(); ok && parsed.User.Username() != "" {
				return explicit, nil
			}
		}
		if username != "" && password != "" {
			return withCredentials(parsed, database, username, password, authSource), nil
		}
		return "", nil
	}
	if username != "" && password != "" {
		host := env("MONGODB_HOST", "localhost")
		port := env("MONGODB_PORT", "27017")
		parsed, _ := url.Parse(fmt.Sprintf("mongodb://%s:%s/%s", host, port, url.PathEscape(database)))
		return withCredentials(parsed, database, username, password, authSource), nil
	}
	return "", nil
}

func withCredentials(parsed *url.URL, database, username, password, authSource string) string {
	parsed.User = url.UserPassword(username, password)
	if parsed.Path == "" || parsed.Path == "/" {
		parsed.Path = "/" + database
	}
	q := parsed.RawQuery
	if !strings.Contains(q, "authSource=") {
		if q != "" {
			q += "&"
		}
		q += "authSource=" + url.QueryEscape(authSource)
	}
	parsed.RawQuery = q
	return parsed.String()
}

func corsOrigins(raw string) []string {
	if strings.TrimSpace(raw) == "" {
		raw = "http://localhost:3000,http://127.0.0.1:3000"
	}
	var out []string
	for _, item := range strings.Split(raw, ",") {
		origin := strings.TrimRight(strings.TrimSpace(item), "/")
		if origin != "" && origin != "*" {
			out = append(out, origin)
		}
	}
	return out
}

func env(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok && value != "" {
		return value
	}
	return fallback
}

// envAllowEmpty keeps an explicitly empty value (e.g. S3_SERVER_SIDE_ENCRYPTION=).
func envAllowEmpty(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok {
		return value
	}
	return fallback
}

func integer(key string, fallback int) int {
	if value, err := strconv.Atoi(strings.TrimSpace(os.Getenv(key))); err == nil {
		return value
	}
	return fallback
}

func boolean(key string, fallback bool) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "1", "true", "yes", "on", "y", "t":
		return true
	case "0", "false", "no", "off", "n", "f":
		return false
	}
	return fallback
}

func durationSeconds(key string, fallback int) time.Duration {
	return time.Duration(integer(key, fallback)) * time.Second
}

func durationMillis(key string, fallback int) time.Duration {
	return time.Duration(integer(key, fallback)) * time.Millisecond
}

func durationFloatSeconds(key string, fallback, minimum float64) time.Duration {
	value := fallback
	if parsed, err := strconv.ParseFloat(strings.TrimSpace(os.Getenv(key)), 64); err == nil {
		value = parsed
	}
	if value < minimum {
		value = minimum
	}
	return time.Duration(value * float64(time.Second))
}
