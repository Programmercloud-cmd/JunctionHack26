"""Building-scoped persisted turns; conversation resolves intent, never creates evidence."""
from copy import deepcopy
import time
import uuid
from .documents import DocumentError


RECONSTRUCTION_STARTED = "I’ll start 3D reconstruction for this set of plans."
RECONSTRUCTION_ALREADY_RUNNING = "3D reconstruction is already running for this set of plans."

# Earlier app versions saved these fixed notices directly in chat and job records.
_LEGACY_RECONSTRUCTION_NOTICES = {
    "Ich starte die 3D-Erstellung für diese Plangruppe.": RECONSTRUCTION_STARTED,
    "Für diese Plangruppe läuft bereits eine 3D-Erstellung.": RECONSTRUCTION_ALREADY_RUNNING,
}


def localize_reconstruction_notice(record, field):
    if record.get("reconstruction_job_id") and isinstance(record.get(field), str):
        record[field] = _LEGACY_RECONSTRUCTION_NOTICES.get(record[field], record[field])
    return record


def question_context(store,document,request):
    if request.conversation_id and request.conversation_id!=document.id:
        raise DocumentError("Conversation belongs to a different building.",422)
    if request.active_page is not None and not any(page.number == request.active_page for page in document.pages):
        raise DocumentError("The selected page does not belong to this plan revision.", 422)
    messages=store.conversation(document.id)
    if request.reply_to:
        parent=next((m for m in messages if m.get("id")==request.reply_to),None)
        if not parent or parent.get("role")!="assistant":
            raise DocumentError("The referenced conversation turn is unavailable in this building.",422)
        if request.clarification_response and (parent.get("answer") or {}).get("status")!="clarification":
            raise DocumentError("A clarification response must refer to a clarification turn.",422)
    elif request.clarification_response:
        raise DocumentError("Choose the clarification turn being answered.",422)
    return {"conversation_id":document.id,"messages":deepcopy(messages),"reply_to":request.reply_to,
            "clarification_response":request.clarification_response,
            "active_page":request.active_page,
            "evidence_rule":"Prior answers and interpretations are fallible context; inspect originals for each answer."}


def user_message(document,request,job_id=None):
    return {"id":uuid.uuid4().hex,"role":"user","question":request.question,
        "clarification_response":request.clarification_response,"reply_to":request.reply_to,
        "revision_id":document.revision_id,"job_id":job_id,"request_id":request.request_id,"timestamp":time.time()}


def assistant_message(document,answer,job_id=None,reply_to=None):
    return {"id":uuid.uuid4().hex,"role":"assistant","answer":answer.model_dump(mode="json"),
            "revision_id":answer.answered_revision_id or document.revision_id,"job_id":job_id,
            "reply_to":reply_to,"timestamp":time.time()}


def reconstruction_message(document, text, reconstruction_job_id, job_id, reply_to):
    return {"id": uuid.uuid4().hex, "role": "assistant", "text": text,
            "reconstruction_job_id": reconstruction_job_id, "revision_id": document.revision_id,
            "job_id": job_id, "reply_to": reply_to, "timestamp": time.time()}
