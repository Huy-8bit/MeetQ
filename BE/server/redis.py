import redis.asyncio as redis
from typing import Optional
import logging

logger = logging.getLogger(__name__)

async def create_redis_client(url: str) -> redis.Redis:
    """Create and return an async Redis client."""
    client = redis.from_url(url, decode_responses=True)
    return client

async def ping_redis(client: redis.Redis) -> bool:
    """Ping Redis to check connectivity."""
    try:
        return await client.ping()
    except Exception as e:
        logger.error(f"Redis ping failed: {e}")
        return False

async def close_redis(client: redis.Redis):
    """Close Redis connection."""
    try:
        await client.aclose()
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")

async def refresh_ttl(client: redis.Redis, key: str, ttl_seconds: int):
    """Helper to set expiration on a key."""
    await client.expire(key, ttl_seconds)
