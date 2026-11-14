"""Content-free reconstruction diagnostics through the existing server logger."""
import json
import logging
import uuid

from google.genai.errors import APIError
import httpx2
from pydantic import ValidationError

from .building import BuildingDescription
from .documents import DocumentError
from .providers.gemini import ProviderError


LOGGER = logging.getLogger("blueprint.reconstruction")
PHASES = {"provider", "description", "generation", "artifact"}
HTTP_STATUSES = {400, 401, 403, 404, 408, 409, 413, 415, 422, 429, 500, 502, 503, 504}
VALIDATION_TYPES = {
    "json_invalid", "missing", "extra_forbidden", "literal_error", "model_type", "model_attributes_type",
    "list_type", "dict_type", "string_type", "float_type", "float_parsing", "int_type", "int_parsing",
    "int_from_float", "bool_type", "bool_parsing", "finite_number", "value_error", "assertion_error",
    "too_short", "too_long", "greater_than", "greater_than_equal", "less_than", "less_than_equal",
}
MESSAGES = {
    "provider_timeout": "The reconstruction provider timed out. Retry the request; no model was saved.",
    "provider_auth": "The reconstruction provider rejected access. Check the selected model and API credentials; no model was saved.",
    "provider_quota": "The reconstruction provider is rate-limited or out of quota. Check quota or retry later; no model was saved.",
    "provider_request": "The reconstruction provider rejected or could not complete the request. Check model access and service availability; no model was saved.",
    "provider_failure": "The reconstruction provider could not complete the request. Retry or check provider availability; no model was saved.",
    "response_json": "The reconstruction provider returned invalid JSON. Retry the request; no model was saved and no source-quality conclusion was made.",
    "response_schema": "The reconstruction description failed structural validation. Retry the request; no model was saved and no source-quality conclusion was made.",
    "generation_failure": "The description could not be converted into IFC. Retry or report the diagnostic reference; no model was saved.",
    "artifact_failure": "The generated IFC could not be validated or reopened. Retry or report the diagnostic reference; no model was saved.",
    "unexpected_failure": "Reconstruction could not complete. Retry or report the diagnostic reference; no model was saved.",
}


def _schema_fields():
    fields = set()

    def visit(node):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                fields.update(properties)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(BuildingDescription.model_json_schema())
    return fields


SCHEMA_FIELDS = _schema_fields()


def _validation_summary(error):
    result = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        code = item.get("type")
        result.append({
            "type": code if code in VALIDATION_TYPES else "validation_error",
            "location": [part if type(part) is int and part >= 0 else part if type(part) is str and part in SCHEMA_FIELDS else "field"
                         for part in item.get("loc", ())],
        })
    return result


def reconstruction_error(error, phase):
    """Record only allowlisted metadata; preserve trusted application error boundaries.

    Never stringify exceptions, log tracebacks, or retain provider/Pydantic messages,
    values, contexts, request URLs, source names or response bodies.
    """
    phase = phase if phase in PHASES else "unknown"
    known = isinstance(error, (DocumentError, ProviderError))
    status = error.status if known else error.code if isinstance(error, APIError) else None
    status = status if type(status) is int and status in HTTP_STATUSES else None
    details = {}
    if known:
        category = "application_rejection" if isinstance(error, DocumentError) else "provider_output_limit" if getattr(error,"category",None)=="provider_output_limit" else "provider_failure"
        error_type = "DocumentError" if isinstance(error, DocumentError) else "ProviderError"
    elif isinstance(error,json.JSONDecodeError):
        category="response_json"
        error_type="JSONDecodeError"
    elif isinstance(error, ValidationError):
        details["validation"] = _validation_summary(error)
        category = "response_json" if any(item["type"] == "json_invalid" for item in details["validation"]) else "response_schema"
        category = {"generation":"generation_failure", "artifact":"artifact_failure"}.get(phase,category)
        error_type = "ValidationError"
    elif isinstance(error, (httpx2.TimeoutException, TimeoutError)):
        category = {"generation":"generation_failure", "artifact":"artifact_failure"}.get(phase,"provider_timeout")
        error_type = "TimeoutError"
    elif isinstance(error, APIError):
        category = "provider_timeout" if status in {408,504} else "provider_auth" if status in {401,403} else "provider_quota" if status == 429 else "provider_request"
        error_type = "APIError"
    else:
        category = {"provider":"provider_failure", "description":"response_schema", "generation":"generation_failure", "artifact":"artifact_failure"}.get(phase,"unexpected_failure")
        error_type = "UnexpectedError"
    diagnostic_id = uuid.uuid4().hex
    event = {"event":"reconstruction_failed", "diagnostic_id":diagnostic_id, "phase":phase,
             "category":category, "error_type":error_type, **details}
    if status is not None:
        event["http_status"] = status
    try:
        LOGGER.warning("%s", json.dumps(event, sort_keys=True))
    except Exception:
        # A logging handler failure must not replace the original operational error.
        pass
    if known:
        error.diagnostic_id=diagnostic_id
        error.category=category
        error.phase=phase
        return error
    result = ProviderError(f"{MESSAGES[category]} [{phase}/{category}; reference {diagnostic_id}]")
    result.diagnostic_id = diagnostic_id
    result.category = category
    result.phase = phase
    return result
