import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import appsettings, assistant_ai, audit, utils
from ..auth import get_current_admin, get_current_user
from ..config import BASE_DIR
from ..database import get_db
from ..models import User
from ..models_p9 import AssistantAction, AssistantMessage, AssistantUsage

router = APIRouter(prefix="/assistant", tags=["assistant"])

KNOWLEDGE_PATHS = [BASE_DIR.parent / "RESUME_PROJET.md"]
MAX_HISTORY = 20
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
NOT_FOUND_PREFIX = "Je n'ai pas trouvé"

STOPWORDS = {
    "les", "des", "une", "que", "qui", "quoi", "est", "sont", "pour", "dans", "avec", "sur", "par",
    "pas", "comment", "peut", "puis", "fait", "faire", "dois", "veux", "vais", "mon", "mes", "ses",
    "the", "and", "aux", "ces", "cette", "elle", "il", "je", "tu", "nous", "vous", "ils", "quel",
    "quelle", "quels", "quelles", "ou", "donc", "mais", "car", "ainsi", "tout", "tous", "plus",
}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(min_length=1, max_length=60)


class Proposal(BaseModel):
    id: int
    action: str
    summary: str


class ChatResponse(BaseModel):
    reply: str
    source: Literal["claude", "local"]
    message_id: Optional[int] = None
    proposals: List[Proposal] = []
    unanswered: bool = False


def _load_knowledge() -> str:
    parts = []
    for path in KNOWLEDGE_PATHS:
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n\n".join(parts)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _keywords(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _normalize(text)) if w not in STOPWORDS}


def _local_answer(question: str, knowledge: str) -> Tuple[str, bool]:
    """Recherche par mots-clés dans la documentation. Renvoie (réponse, trouvée)."""
    if not knowledge:
        return "La documentation de l'application est introuvable côté serveur.", False

    terms = _keywords(question)
    scored = []
    heading = ""
    for block in re.split(r"\n\s*\n", knowledge):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            heading = block.lstrip("# ").strip()
            continue
        score = len(terms & _keywords(block)) + 2 * len(terms & _keywords(heading))
        if score:
            scored.append((score, heading, block))

    if not scored:
        return (
            f"{NOT_FOUND_PREFIX} de passage correspondant dans la documentation. "
            "Essayez avec d'autres mots (ex. « réservation », « EPI », « inventaire », « transfert », « droits ») : "
            "votre question a été transmise à l'administrateur pour améliorer l'aide.",
            False,
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    parts = [f"**{h}**\n{b}" if h else b for _, h, b in scored[:3]]
    return "Voici ce que dit la documentation :\n\n" + "\n\n".join(parts), True


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


@router.get("/status")
def assistant_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"ai_enabled": assistant_ai.has_credentials(), "model": assistant_ai.model_name() if assistant_ai.has_credentials() else None,
            "rate_per_minute": appsettings.get_int(db, "assistant.rate_per_minute"), "daily_token_cap": appsettings.get_int(db, "assistant.daily_token_cap")}


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    messages = payload.messages[-MAX_HISTORY:]
    while messages and messages[0].role != "user":
        messages = messages[1:]
    if not messages or messages[-1].role != "user":
        return ChatResponse(reply="Posez-moi une question sur l'application.", source="local")

    blocked = assistant_ai.check_quota(db, current_user)
    if blocked:
        db.commit()
        _fail(blocked, status.HTTP_429_TOO_MANY_REQUESTS)

    question = messages[-1].content
    knowledge = _load_knowledge()
    source, reply, unanswered, tools, proposals, tokens = "local", "", False, [], [], 0

    if assistant_ai.has_credentials():
        try:
            result = assistant_ai.run_chat(db, current_user, [{"role": m.role, "content": m.content} for m in messages], knowledge)
            source, reply, unanswered, tools, proposals, tokens = "claude", result.text, result.unanswered, result.tools, result.proposals, result.tokens
        except Exception:
            db.rollback()

    if source == "local":
        reply, found = _local_answer(question, knowledge)
        unanswered = not found

    entry = AssistantMessage(user_id=current_user.id, question=question[:1000], answer=reply[:4000], source=source,
                             tools_used=json.dumps(tools) if tools else None, unanswered=unanswered, created_at=utils.now())
    db.add(entry)
    db.flush()
    for row in proposals:
        row.message_id = entry.id
    usage = assistant_ai.usage_today(db, current_user)
    usage.messages += 1
    usage.tokens += tokens
    db.commit()
    return ChatResponse(reply=reply, source=source, message_id=entry.id, unanswered=unanswered,
                        proposals=[Proposal(id=p.id, action=p.action, summary=p.summary) for p in proposals])


# ------------------------------------------------------------------ retours d'utilité

class FeedbackIn(BaseModel):
    message_id: int
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(default=None, max_length=500)


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(payload: FeedbackIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(AssistantMessage).filter(AssistantMessage.id == payload.message_id, AssistantMessage.user_id == current_user.id).first()
    if row is None:
        _fail("Message introuvable", status.HTTP_404_NOT_FOUND)
    row.feedback = payload.rating
    row.feedback_comment = payload.comment
    db.commit()


@router.get("/insights")
def insights(days: int = 30, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    since = utils.now() - timedelta(days=max(1, min(days, 365)))
    rows = db.query(AssistantMessage).filter(AssistantMessage.created_at >= since).all()
    names = {u.id: u.full_name for u in db.query(User)}
    usage = db.query(AssistantUsage).filter(AssistantUsage.day >= since.strftime("%Y-%m-%d")).all()
    return {
        "days": days, "messages": len(rows),
        "by_source": {s: sum(1 for r in rows if r.source == s) for s in ("claude", "local")},
        "feedback": {"up": sum(1 for r in rows if r.feedback == "up"), "down": sum(1 for r in rows if r.feedback == "down")},
        "unanswered": [{"id": r.id, "question": r.question, "user": names.get(r.user_id), "created_at": r.created_at}
                       for r in sorted((r for r in rows if r.unanswered), key=lambda r: -r.id)[:100]],
        "disliked": [{"id": r.id, "question": r.question, "answer": (r.answer or "")[:300], "comment": r.feedback_comment}
                     for r in rows if r.feedback == "down"][:50],
        "tokens": sum(u.tokens for u in usage),
    }


# ------------------------------------------------------------------ actions proposées : confirmation explicite

def _own_pending(db: Session, user: User, action_id: int) -> AssistantAction:
    assistant_ai.expire_old(db)
    row = db.query(AssistantAction).filter(AssistantAction.id == action_id).first()
    if row is None or row.user_id != user.id:
        _fail("Proposition introuvable", status.HTTP_404_NOT_FOUND)
    if row.status != "pending":
        _fail("Cette proposition n'est plus en attente" + (" (expirée)" if row.result == "expirée" else ""))
    return row


def _perform(db: Session, user: User, row: AssistantAction) -> dict:
    from . import loans, maintenance

    params = json.loads(row.params)
    if row.action == "create_reservation":
        response = Response()
        created = loans.create_loan(
            loans.LoanCreateIn(tool_id=params["tool_id"], site=params.get("site"), start_datetime=datetime.fromisoformat(params["start_datetime"]),
                               end_datetime_planned=datetime.fromisoformat(params["end_datetime_planned"])),
            response, db, user,
        )
        return {"message": "Réservation créée", "loan_id": created["id"], "warning": response.headers.get("x-warning")}
    if row.action == "report_problem":
        created = maintenance.report_problem(maintenance.TicketIn(**params), db, user)
        return {"message": "Problème signalé", "ticket": created.get("id") if isinstance(created, dict) else None}
    if row.action == "cancel_reservation":
        loans.cancel_loan(params["loan_id"], db, user)
        return {"message": "Réservation annulée"}
    raise HTTPException(status_code=400, detail="Action inconnue")


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = _own_pending(db, current_user, action_id)
    row.status = "confirmed"
    db.commit()
    try:
        outcome = _perform(db, current_user, row)
    except HTTPException as exc:
        db.rollback()
        row = db.query(AssistantAction).filter(AssistantAction.id == action_id).first()
        row.status, row.decided_at, row.result = "failed", utils.now(), str(exc.detail)[:300]
        db.commit()
        raise
    row = db.query(AssistantAction).filter(AssistantAction.id == action_id).first()
    row.decided_at, row.result = utils.now(), json.dumps(outcome, default=str)[:500]
    audit.record(db, "assistant_action_confirmed", current_user.id, "assistant_action", row.id, request, {"action": row.action})
    db.commit()
    return outcome


@router.post("/actions/{action_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_action(action_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = _own_pending(db, current_user, action_id)
    row.status, row.decided_at = "cancelled", utils.now()
    db.commit()


# ------------------------------------------------------------------ extraction depuis une photo

@router.post("/extract-from-photo")
def extract_from_photo(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role.value == "gars_chantier":
        _fail("Réservé aux gestionnaires", status.HTTP_403_FORBIDDEN)
    if file.content_type not in IMAGE_TYPES:
        _fail("Format d'image non pris en charge (JPEG, PNG ou WebP)")
    content = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        _fail("Image trop volumineuse (5 Mo maximum)")
    if not assistant_ai.has_credentials():
        _fail("L'extraction par IA n'est pas disponible (clé ANTHROPIC_API_KEY non configurée)", status.HTTP_503_SERVICE_UNAVAILABLE)
    blocked = assistant_ai.check_quota(db, current_user)
    if blocked:
        _fail(blocked, status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        data = assistant_ai.extract_from_photo(content, file.content_type)
    except Exception:
        _fail("L'analyse de la photo a échoué, réessayez", status.HTTP_502_BAD_GATEWAY)
    usage = assistant_ai.usage_today(db, current_user)
    usage.tokens += 1500
    db.commit()
    return {**data, "notice": "Suggestions à vérifier : rien n'est enregistré tant que vous ne validez pas le formulaire."}
