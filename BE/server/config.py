from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str
    openai_realtime_model: str = "gpt-realtime"
    openai_realtime_transcription_model: str = "gpt-4o-transcribe"
    openai_summary_model: str = "gpt-4o-mini"
    meeting_summary_language: str = "en"
    meeting_summary_max_source_items: int = 240
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_channel_gateway_control: str = "brseai:v1:gateway:control"
    redis_channel_interpreter_events: str = "brseai:v1:interpreter:events"

    # MongoDB historical persistence (Redis remains hot runtime state)
    mongodb_url: Optional[str] = None
    mongodb_host: str = "localhost"
    mongodb_port: int = 27017
    mongodb_database: str = "brseai"
    mongodb_username: Optional[str] = None
    mongodb_password: Optional[str] = None
    mongodb_auth_source: Optional[str] = None
    mongodb_server_selection_timeout_ms: int = 500
    mongodb_connect_timeout_ms: int = 500
    
    # JWT
    room_jwt_secret: str
    room_token_ttl_seconds: int = 86400
    room_meeting_duration_seconds: int = 3600  # 60 minutes logical meeting duration
    room_max_participants: int = 0  # 0 = no backend participant cap enforcement
    
    # LiveKit
    livekit_api_key: str
    livekit_api_secret: str
    livekit_ws_url_public: str = "ws://localhost:7880"
    livekit_ws_url_internal: str = "ws://localhost:7880"
    public_app_url: str = "http://localhost:3000"
    public_gateway_url: str = "http://localhost:8000"
    public_gateway_ws_url: Optional[str] = None
    realtime_input_sample_rate: int = 24000
    realtime_output_sample_rate: int = 24000
    # Per-speaker line isolation (server.service.livekit_lines)
    livekit_line_isolation_enabled: bool = True
    livekit_line_lookahead_ms: int = 120
    livekit_line_crosstalk_correlation: float = 0.75
    livekit_line_crosstalk_dominance_db: float = 4.0
    ws_stale_timeout_seconds: int = 90
    ws_stale_sweep_interval_seconds: int = 15

    # Telegram notifications
    telegram_notifications_enabled: bool = False
    telegram_notify_room_created: bool = True
    telegram_notify_participant_joined: bool = True
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_request_timeout_seconds: float = 3.0

    # Admin portal (username + password, separate from Google user sign-in).
    # The portal is disabled until ADMIN_USERNAME and a password are set.
    # Prefer ADMIN_PASSWORD_HASH (python -m server.service.auth.passwords);
    # ADMIN_PASSWORD (plain text) is for local development.
    admin_username: Optional[str] = None
    admin_password_hash: Optional[str] = None
    admin_password: Optional[str] = None
    admin_session_ttl_seconds: int = 43200

    # User sign-in (Google Identity Services ID tokens).
    google_client_id: Optional[str] = None
    # Optional comma-separated email domains allowed to sign in (empty = any verified Google account).
    google_allowed_domains: Optional[str] = None
    user_session_ttl_seconds: int = 1209600  # 14 days
    # Room and test endpoints require a signed-in user. Turn off only for local experiments.
    user_auth_required: bool = True
    # Session cookies are Secure by default; set false only for plain-http local setups (Safari).
    auth_cookie_secure: bool = True
    # Retention of BRSE ops events (relay traces / AI errors) in MongoDB.
    ops_event_retention_days: int = 30

    # Meeting archive + recording (docs/meeting-recording-and-retention.md).
    # Private S3 bucket for recordings and archived meeting JSON. Credentials come from
    # the standard AWS chain (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or an instance role).
    meeting_archive_bucket: Optional[str] = None
    meeting_archive_prefix: str = "meetings"
    aws_region: Optional[str] = None
    # S3-compatible endpoint (local MinIO). Empty for AWS S3.
    s3_endpoint_url: Optional[str] = None
    # Endpoint the browser can reach, used only to sign playback/download URLs (local MinIO).
    s3_public_endpoint_url: Optional[str] = None
    s3_force_path_style: bool = False
    # Per-object server-side encryption header. The AWS bucket also enforces SSE-S3 by
    # default (Terraform); local MinIO without KMS needs this empty.
    s3_server_side_encryption: str = "AES256"
    # Local development only: create the (private) bucket at start-up. On AWS the
    # bucket is provisioned by Terraform (infra/terraform/storage).
    s3_create_bucket: bool = False
    # Default retention for new meeting archives until an admin changes it in the portal.
    default_meeting_retention_days: int = 7
    # Start/Stop Recording in meetings (LiveKit Egress writes MP4 to the archive bucket).
    meeting_recording_enabled: bool = True
    recording_layout: str = "speaker"
    recording_url_ttl_seconds: int = 600
    # Background jobs.
    recording_poll_interval_seconds: float = 3.0
    archive_poll_interval_seconds: float = 20.0
    archive_cleanup_interval_seconds: float = 3600.0
    # How long archiving waits for the final summary after a meeting ends.
    archive_summary_wait_seconds: int = 300
    deployment_environment: str = "local"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

def get_settings() -> Settings:
    return Settings()
