# services/api/app/routes/feedback.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.jwt import get_current_user
from app.memory.postgres import AsyncSessionLocal

router = APIRouter()

class FeedbackRequest(BaseModel):
    session_id: str
    message_id: int # ID of the assistant message from chat_history
    score: int # 1 (Like) or -1 (Dislike)
    comment: str = None

@router.post("/")
async def submit_feedback(
    req: FeedbackRequest,
    user: dict = Depends(get_current_user)
):
    """
    Submit user feedback for an AI response.
    """
    try:
        async with AsyncSessionLocal() as session:
            # We create a simple feedback table or add a column to chat_history.
            # Here, let's assume a 'feedback' table exists (simple raw SQL for demo)
            await session.execute(
                text("""
                INSERT INTO feedback (session_id, user_id, message_id, score, comment)
                VALUES (:sid, :uid, :mid, :score, :comment)
                """),
                {
                    "sid": req.session_id,
                    "uid": user["id"],
                    "mid": req.message_id,
                    "score": req.score,
                    "comment": req.comment
                }
            )
            await session.commit()
            return {"status": "recorded"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
