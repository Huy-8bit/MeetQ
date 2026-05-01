from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str
    openai_realtime_model: str = "gpt-realtime-1.5"
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_channel_gateway_control: str = "brseai:v1:gateway:control"
    redis_channel_interpreter_events: str = "brseai:v1:interpreter:events"
    
    # JWT
    room_jwt_secret: str
    room_token_ttl_seconds: int = 86400
    room_meeting_duration_seconds: int = 1800  # 30 minutes logical meeting duration
    room_max_participants: int = 0  # 0 = no backend participant cap enforcement
    
    # LiveKit
    livekit_api_key: str
    livekit_api_secret: str
    livekit_ws_url_public: str = "ws://localhost:7880"
    livekit_ws_url_internal: str = "ws://localhost:7880"
    public_app_url: str = "http://localhost:3000"
    public_gateway_url: str = "http://localhost:8000"
    public_gateway_ws_url: Optional[str] = None
    realtime_input_sample_rate: int = 16000
    realtime_output_sample_rate: int = 24000
    ws_stale_timeout_seconds: int = 90
    ws_stale_sweep_interval_seconds: int = 15

    # Telegram notifications
    telegram_notifications_enabled: bool = False
    telegram_notify_room_created: bool = True
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_request_timeout_seconds: float = 3.0
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

def get_settings() -> Settings:
    return Settings()
