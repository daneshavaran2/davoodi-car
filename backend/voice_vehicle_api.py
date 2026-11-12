"""Optional voice parsing router; include in existing FastAPI app.

    from voice_vehicle_api import router as voice_router
    app.include_router(voice_router)

If an existing /api/parse-voice route exists, modify that route to call
recognize_vehicle() rather than registering a duplicate.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from vehicle_recognition import recognize_vehicle

router = APIRouter(tags=["voice-vehicle"])

class VoiceText(BaseModel):
    text: str = Field(min_length=1, max_length=3000)

@router.post("/api/recognize-vehicle")
def recognize(payload: VoiceText):
    return recognize_vehicle(payload.text)
