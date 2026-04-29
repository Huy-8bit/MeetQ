from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # JWT
    room_jwt_secret: str
    room_token_ttl_seconds: int = 86400
    
    # LiveKit
    livekit_api_key: str
    livekit_api_secret: str
    livekit_ws_url_public: str = "ws://18.142.51.37:7880"
    livekit_ws_url_internal: str = "ws://18.142.51.37:7880"
    realtime_input_sample_rate: int = 16000
    realtime_output_sample_rate: int = 24000
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

def get_settings() -> Settings:
    return Settings()
