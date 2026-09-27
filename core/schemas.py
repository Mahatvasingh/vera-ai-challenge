from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field


ALLOWED_CTX_SCOPES = ("category", "merchant", "customer", "trigger")


class CtxBody(BaseModel):
    # Deliberately `str`, not `Literal[...]`: an invalid scope must reach our
    # handler so we can return the testing brief's documented 400 shape
    # ({"accepted": false, "reason": "invalid_scope", ...}) instead of
    # FastAPI/pydantic's default 422 validation error.
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str


class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = []


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


class ComposedAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: List[str] = []
    body: str
    cta: Literal["binary", "open_ended", "none"]
    suppression_key: str
    rationale: str


class TeardownBody(BaseModel):
    # Judge posts this (optionally) at end of test; body is empty/ignored.
    reason: Optional[str] = None