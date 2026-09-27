import os
import time
import traceback
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from typing import Dict, Any, List, Optional, Tuple

from core.schemas import CtxBody, TickBody, ReplyBody, TeardownBody, ALLOWED_CTX_SCOPES
from core.composer import compose_message, _active_offers
from core.guardrails import is_verbatim_repeat

load_dotenv()

app = FastAPI(title="magicpin Vera AI Assistant")
START_TIME = time.time()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Per challenge-testing-brief.md §2.1, a malformed /v1/context body must get
    a 400 with {"accepted": false, "reason": "...", "details": "..."} rather
    than FastAPI's default 422. Other endpoints aren't given a contractual
    error shape in the brief, so they keep the default 422 behavior.
    """
    if request.url.path == "/v1/context":
        return JSONResponse(
            status_code=400,
            content={
                "accepted": False,
                "reason": "invalid_payload",
                "details": str(exc.errors()) if hasattr(exc, "errors") else str(exc),
            },
        )
    return JSONResponse(status_code=422, content={"detail": str(exc)})

MAX_ACTIONS_PER_TICK = 20  # per testing-brief §5

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
contexts: Dict[tuple, Dict[str, Any]] = {}              # (scope, context_id) -> {version, payload}
conversations: Dict[str, List[Dict[str, str]]] = {}     # conversation_id -> turns [{from, msg}]
conv_meta: Dict[str, Dict[str, Any]] = {}                # conversation_id -> {merchant_id, customer_id, trigger_id}

fired_triggers: set = set()                              # trigger_ids already turned into a tick action
fired_suppression_keys: Dict[str, str] = {}               # suppression_key -> conversation_id that used it

auto_reply_tracker: Dict[str, int] = {}                   # identity_key -> canned auto-reply hit count
raw_msg_history: Dict[str, List[str]] = {}                # identity_key -> raw inbound messages (for verbatim-repeat)
boundary_given: set = set()                               # conversation_ids where we've already set a hostility boundary


def _identity_key(merchant_id: Optional[str], customer_id: Optional[str]) -> str:
    return f"{merchant_id or '?'}:{customer_id or '-'}"


def _get_payload(scope: str, context_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not context_id:
        return None
    entry = contexts.get((scope, context_id))
    return entry.get("payload") if entry else None


def _recent_vera_bodies(merchant_id: Optional[str], limit: int = 3) -> List[str]:
    """Recent bodies we've already sent this merchant, across conversations, for anti-repetition."""
    if not merchant_id:
        return []
    out = []
    for conv_id, meta in conv_meta.items():
        if meta.get("merchant_id") != merchant_id:
            continue
        for turn in conversations.get(conv_id, []):
            if turn.get("from") in ("vera", "bot"):
                out.append(turn.get("msg", ""))
    return out[-limit:]


@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _), _ in contexts.items():
        counts[scope] = counts.get(scope, 0) + 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "VEXA AI",
        "team_members": ["Mahatva Singh"],
        "model": "gpt-4o-mini",
        "approach": "Per-trigger-kind grounded deterministic dispatch validated by strict quant-token grounding and taboo filtering, augmented with OpenAI gpt-4o-mini evaluation and formatting; suppression-key and fired-trigger deduplication across ticks; multi-turn identity-keyed auto-reply and hostile intent handling.",
        "contact_email": "mahatva844@gmail.com",
        "version": "1.1.0",
        "submitted_at": datetime.utcnow().isoformat() + "Z"
    }

@app.post("/v1/context")
async def push_context(body: CtxBody):
    if body.scope not in ALLOWED_CTX_SCOPES:
        return JSONResponse(
            status_code=400,
            content={
                "accepted": False,
                "reason": "invalid_scope",
                "details": f"scope must be one of {list(ALLOWED_CTX_SCOPES)}, got '{body.scope}'",
            },
        )

    key = (body.scope, body.context_id)
    cur = contexts.get(key)

    # Per testing-brief §2.1/§5: idempotent by (context_id, version).
    # - Same version re-posted => no-op, but still ack as accepted (idempotent,
    #   not an error) so the judge doesn't see a false rejection on retries.
    # - Strictly older version => genuine conflict, must be a 409 with the
    #   documented {"accepted": false, "reason": "stale_version", ...} shape.
    if cur and body.version == cur["version"]:
        return {
            "accepted": True,
            "ack_id": f"ack_{body.context_id}_v{body.version}",
            "stored_at": datetime.utcnow().isoformat() + "Z",
            "note": "idempotent_replay",
        }
    if cur and cur["version"] > body.version:
        return JSONResponse(
            status_code=409,
            content={
                "accepted": False,
                "reason": "stale_version",
                "current_version": cur["version"],
            },
        )

    contexts[key] = {"version": body.version, "payload": body.payload}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.utcnow().isoformat() + "Z"
    }


@app.post("/v1/teardown")
async def teardown(body: TeardownBody = None):
    """Optional: judge calls this at end of test. Wipe all state per privacy §11."""
    contexts.clear()
    conversations.clear()
    conv_meta.clear()
    fired_triggers.clear()
    fired_suppression_keys.clear()
    auto_reply_tracker.clear()
    raw_msg_history.clear()
    boundary_given.clear()
    return {"status": "wiped"}


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []

    for trg_id in body.available_triggers:
        if len(actions) >= MAX_ACTIONS_PER_TICK:
            break

        # Never re-fire a trigger we've already turned into an action —
        # reusing a conversation_id at /v1/tick is invalid per the testing brief,
        # and a trigger should only produce one send.
        if trg_id in fired_triggers:
            continue

        trg_payload = _get_payload("trigger", trg_id)
        if not trg_payload:
            continue

        suppression_key = trg_payload.get("suppression_key", f"suppress_{trg_id}")
        if suppression_key in fired_suppression_keys:
            fired_triggers.add(trg_id)
            continue

        merchant_id = trg_payload.get("merchant_id") or trg_payload.get("payload", {}).get("merchant_id")
        merchant_ctx = _get_payload("merchant", merchant_id)
        if not merchant_ctx:
            continue

        cat_slug = merchant_ctx.get("category_slug")
        category_ctx = _get_payload("category", cat_slug) or {}

        payload_dict = trg_payload.get("payload", {}) or {}
        customer_id = trg_payload.get("customer_id") or payload_dict.get("customer_id")
        customer_ctx = _get_payload("customer", customer_id) if customer_id else None
        

        try:
            composed = compose_message(
                category=category_ctx,
                merchant=merchant_ctx,
                trigger=trg_payload,
                customer=customer_ctx,
                avoid_bodies=_recent_vera_bodies(merchant_id),
            )
        except Exception:
            # One bad context/trigger combo should never take down the whole tick.
            traceback.print_exc()
            continue

        if not composed.get("body"):
            continue

        conv_id = f"conv_{merchant_id}_{trg_id}"
        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": "merchant_on_behalf" if customer_id else "vera",
            "trigger_id": trg_id,
            "template_name": "vera_customer_on_behalf_v1" if customer_id else "vera_generic_v1",
            "template_params": [merchant_ctx.get("identity", {}).get("name", "Merchant")],
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": suppression_key,
            "rationale": composed["rationale"]
        }
        actions.append(action)

        fired_triggers.add(trg_id)
        fired_suppression_keys[suppression_key] = conv_id
        conv_meta[conv_id] = {
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "trigger_id": trg_id,
            "category_slug": cat_slug,
        }
        conversations.setdefault(conv_id, []).append({"from": "vera", "msg": composed["body"]})

    return {"actions": actions}


def _boundary_message(merchant_ctx: Optional[Dict[str, Any]]) -> str:
    # Owner first name > business name > no name, so the boundary line still
    # reads personalized (per case-studies.md: generic "Hi" costs merchant-fit
    # points) even in the one flow where we're mostly saying "I'll back off".
    identity = (merchant_ctx or {}).get("identity", {}) or {}
    name = identity.get("owner_first_name") or identity.get("name") or ""
    prefix = f"No problem, {name} — " if name else "No problem — "
    return (
        prefix
        + "I'll stop these updates if you'd like. That other ask is outside what I can help with here; "
          "I'm just here for your Google/WhatsApp business profile if that's ever useful. Reply STOP anytime."
    )


def _default_continuation(merchant_ctx: Optional[Dict[str, Any]], message: str) -> Tuple[str, str]:
    name = (merchant_ctx or {}).get("identity", {}).get("name", "there") if merchant_ctx else "there"
    offer = _active_offers(merchant_ctx or {})
    is_question = "?" in message

    if is_question:
        # Curveball / off-topic question with no keyword match — acknowledge scope,
        # stay on-mission, still leave one concrete next step.
        body = (
            f"Good question — that's a bit outside what I handle directly. "
            f"What I *can* do for {name} right now: keep your Google Business profile fresh. "
            f"Want me to check it and report back?"
        )
        return body, "binary"

    if offer:
        body = f"Got it, {name}! Should I go ahead and put \"{offer[0]}\" live on your Google post now?"
    else:
        body = f"Got it, {name}! Want me to go ahead and publish this update to your Google profile now?"
    return body, "binary"


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    conv_id = body.conversation_id
    raw_msg = body.message.strip()
    msg = raw_msg.lower()

    conversations.setdefault(conv_id, []).append({"from": body.from_role, "msg": body.message})

    meta = conv_meta.get(conv_id, {})
    merchant_id = body.merchant_id or meta.get("merchant_id")
    customer_id = body.customer_id or meta.get("customer_id")
    merchant_ctx = _get_payload("merchant", merchant_id)

    identity_key = _identity_key(merchant_id, customer_id)
    history_before = list(raw_msg_history.get(identity_key, []))
    raw_msg_history.setdefault(identity_key, []).append(raw_msg)

    # --- SCENARIO 1: Canned WhatsApp auto-replies (marker-based OR verbatim repeat) ---
    auto_reply_markers = [
        "thank you for contacting",
        "our team will respond shortly",
        "automated response",
        "hamari team tak",
        "how can we help you"
    ]
    marker_hit = any(marker in msg for marker in auto_reply_markers)
    verbatim_hit = is_verbatim_repeat(raw_msg, history_before, min_hits=3)

    if marker_hit or verbatim_hit:
        count = auto_reply_tracker.get(identity_key, 0) + 1
        auto_reply_tracker[identity_key] = count
        if verbatim_hit or count >= 2:
            return {
                "action": "end",
                "rationale": "Detected repeated canned auto-reply (marker match or 3+ verbatim repeats); exiting to avoid a bot-to-bot loop."
            }
        return {
            "action": "send",
            "body": "Samajh gayi! Agar aap Google Business profile check karna chahein, toh bas batayiye.",
            "cta": "open_ended",
            "rationale": "Single polite follow-up after first suspected auto-reply, before confirming and exiting."
        }

    # --- SCENARIO 2: Hostile / opt-out ---
    stop_words = ["stop", "spam", "abuse", "useless", "don't message", "dont message"]
    has_stop = any(w in msg for w in stop_words)
    has_question = "?" in raw_msg

    if has_stop and has_question:
        # Mixed message: opt-out/hostility PLUS an unrelated ask. Stay on-mission
        # politely rather than either ignoring the ask or hard-ending immediately.
        boundary_given.add(conv_id)
        return {
            "action": "send",
            "body": _boundary_message(merchant_ctx),
            "cta": "none",
            "rationale": "Hostile/opt-out language combined with an unrelated question; set a boundary and stayed on-mission instead of ending or ignoring the question."
        }
    if has_stop:
        return {
            "action": "end",
            "rationale": "Merchant opted out or expressed hostility with no further ask; exiting cleanly."
        }

    # --- SCENARIO 3: Instant intent handoff (action mode) ---
    action_intents = [
        "ok lets do it", "let's do it", "whats next", "what's next", "proceed",
        "join", "karna hai", "yes", "done", "go ahead", "confirm", "sounds good"
    ]
    if any(intent in msg for intent in action_intents):
        name = (merchant_ctx or {}).get("identity", {}).get("name", "") if merchant_ctx else ""
        who = f" for {name}" if name else ""
        return {
            "action": "send",
            "body": f"Done! Maine draft setup kar diya hai{who}. Kya main ise Google profile pe live publish kar doon?",
            "cta": "binary",
            "rationale": "Merchant signaled explicit commitment; switched immediately from qualification to action mode instead of re-qualifying."
        }

    # --- SCENARIO 4: Wait request ---
    if any(w in msg for w in ["wait", "busy", "later", "baad mein"]):
        return {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant requested time; pausing for 30 minutes."
        }

    # --- Default: grounded continuation, with anti-repetition against this conversation ---
    prior_vera_bodies = [t["msg"] for t in conversations.get(conv_id, []) if t.get("from") in ("vera", "bot")]
    candidate_body, candidate_cta = _default_continuation(merchant_ctx, raw_msg)
    if any(candidate_body.strip().lower() == b.strip().lower() for b in prior_vera_bodies):
        candidate_body += " (Just checking in — still there?)"

    return {
        "action": "send",
        "body": candidate_body,
        "cta": candidate_cta,
        "rationale": "No strong signal matched (auto-reply/hostile/intent/wait); gave a grounded next step using merchant context and avoided repeating a prior message."
    }