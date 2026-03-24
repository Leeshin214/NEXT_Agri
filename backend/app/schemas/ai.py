from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AIChatRequest(BaseModel):
    prompt: str
    prompt_type: Optional[str] = None


class AISummarizeChatRequest(BaseModel):
    messages: str
    context: Optional[str] = None


class AISummarizeResponse(BaseModel):
    summary: str


class AIConversationResponse(BaseModel):
    id: UUID
    user_id: UUID
    prompt: str
    response: str
    prompt_type: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
