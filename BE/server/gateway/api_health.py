from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()

@router.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "gateway",
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dependencies": {
            "redis": "ok" # Simplified for now, in a real app might ping Redis
        }
    }
