"""One Hydrogen creator, then two parallel independent reviews, until agreement or interruption."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import hashlib
import json
import os

from pydantic import Field

from .annotations import apply_measurements
from .building import BUILDING_PROMPT, BuildingDescription
from .documents import DocumentError, resolve_reference
from .identities import assign_identities
from .jobs import JobStopped
from .providers.gemini import (RECONSTRUCTION_PATCH_INSTRUCTIONS, RECONSTRUCTION_REVIEW_INSTRUCTIONS,
                               GEOMETRY_ENRICHMENT_INSTRUCTIONS, configured_number)
from .review_render import overlay_views
from .review_schema import DescriptionPatch, ReconstructionReview
from .revisions import apply_patch, apply_enrichment, normalize_views, regression_findings, _validate_all_sources


class RenderReview(ReconstructionReview):
    satisfied: bool = Field(description="True only if this exact reopened model needs no further supported correction for the user's request.")


def candidate_digest(document):
    # Actual reopened mesh geometry is included, rather than just intended polygons.
    data = {"description": document.description.model_dump(mode="json"),
            "elements": [e.model_dump(mode="json") for e in document.scene.elements],
            "floors": [f.model_dump(mode="json") for f in document.scene.floors],
            "user_values": document.user_values}
    content = json.dumps(data, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(content + (document.ifc_bytes or b"")).hexdigest()


def propose(provider, document, review, feedback, annotations, message):
    hook = getattr(provider, "render_candidate", None)
    if callable(hook):
        return hook(document, review=review, feedback=feedback, annotations=annotations, message=message)
    data = {"original_user_message": message, "user_annotations": annotations,
            "annotation_authority": "User-authored instructions and dimensions; never original drawing observations.",
            "validation_feedback": feedback}
    options = dict(thinking_level="high", model=provider.reconstruction_model, include_qa_context=False,
                   timeout_ms=round(configured_number("RECONSTRUCTION_CALL_SECONDS", 300) * 1000),
                   max_tokens=configured_number("RECONSTRUCTION_MAX_TOKENS", 65536, integer=True))
    role = "\nYou are the fixed creator. Two separate reviewers will inspect your generated IFC in parallel. Their combined feedback arrives in the next round."
    if document.description is None:
        return provider._generate(document, message, BUILDING_PROMPT + role, BuildingDescription, extra_data=data, **options)
    data.update(base_revision_id=document.revision_id, description=document.description.model_dump(mode="json"),
                user_values=document.user_values, review=review.model_dump(mode="json") if review else None)
    if review is None:
        from .geometry_requirements import missing_geometry_requests
        data["missing_geometry_requests"] = missing_geometry_requests(document.description)
    return provider._generate(document, message, (RECONSTRUCTION_PATCH_INSTRUCTIONS if review is not None else GEOMETRY_ENRICHMENT_INSTRUCTIONS) +
        "\nCorrect the requested model using the independently reported source findings. Preserve all user-provided provenance. "
        "User annotations identify requests, not evidence observed in the original blueprint." + role, DescriptionPatch,
        extra_views=overlay_views(document, document.scene) if document.scene else [], extra_data=data, **options)


def inspect(provider, document, digest, annotations, message):
    hook = getattr(provider, "review_render", None)
    if callable(hook):
        result = hook(document, candidate_digest=digest, annotations=annotations, message=message)
    else:
        result = provider._generate(document, message, RECONSTRUCTION_REVIEW_INSTRUCTIONS +
            "\nYou are one of two independent reviewers of the creator's exact reopened candidate. Inspect original pages and actual IFC overlays. "
            "Return satisfied only if you need no further supported correction for the original request. "
            "The other reviewer's opinion is intentionally withheld; independently assess the actual candidate. Model satisfaction is not proof of factual accuracy. "
            "Keep unknown dimensions and unresolved features explicit; do not demand invented hidden geometry.", RenderReview,
            thinking_level="high", model=provider.reconstruction_model, include_qa_context=False,
            timeout_ms=round(configured_number("RECONSTRUCTION_REVIEW_SECONDS", 120) * 1000),
            max_tokens=configured_number("RECONSTRUCTION_REVIEW_TOKENS", 16384, integer=True),
            extra_views=overlay_views(document, document.scene),
            extra_data={"candidate_digest": digest, "description": document.description.model_dump(mode="json"),
                        "actual_geometry_inventory": [e.model_dump(exclude={"geometry"}) for e in document.scene.elements],
                        "user_values": document.user_values, "user_annotations": annotations})
    vote = RenderReview.model_validate(result)
    known = {e.id for e in document.scene.elements} | {f.id for f in document.scene.floors}
    for issue in vote.issues:
        resolve_reference(document, issue.source.page, issue.source.source_id, issue.source.source_page)
        if not set(issue.object_ids) <= known:
            raise DocumentError("The render review referenced an unknown model object.", 422)
    return vote


def combined_review(votes):
    issues = []
    for index, vote in enumerate(votes):
        for issue in vote.issues:
            item = issue.model_copy(deep=True)
            item.id = f"reviewer{index + 1}:{item.id}"
            issues.append(item)
    return ReconstructionReview(candidate_supported=all(v.candidate_supported for v in votes), issues=issues,
                                summary="\n".join(v.summary for v in votes))


def parallel_reviews(providers, candidate, digest, annotations, message, guard, update):
    votes = {}
    def review_one(provider, document, marks):
        guard()
        return inspect(provider, document, digest, marks, message)
    # Separate threads/clients and private snapshots: no shared provider state,
    # candidate mutation, or feedback from the sibling reviewer.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="hydrogen-review") as pool:
        futures = {}
        for index, provider in enumerate(providers):
            guard()
            futures[pool.submit(review_one, provider, candidate.snapshot(), deepcopy(annotations))] = index + 1
        pending = set(futures)
        while pending:
            guard()
            done, pending = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=futures.get):
                vote = future.result()
                guard()
                if candidate_digest(candidate) != digest:
                    raise DocumentError("Render candidate changed while being reviewed.", 409)
                votes[futures[future]] = vote
                update(reviewer_votes=[{"reviewer": index, "candidate_digest": digest,
                                         "satisfied": item.satisfied, "candidate_supported": item.candidate_supported,
                                         "summary": item.summary} for index, item in sorted(votes.items())])
        # Exiting the pool also drains failed/stopped rounds before provider reuse
        # or close. In-flight network calls retain their existing request timeouts.
    return [votes[index] for index in (1, 2)]


def run_render(runner, identity, original, message, annotations):
    providers = []
    published = original
    working = original.snapshot()
    feedback = None
    review = None
    round_number = 0
    config = {"pipeline_version": "parallel-hydrogen-v2", "render_model": os.getenv("GEMINI_RENDER_MODEL", "gemini-4-hydrogen"),
              "call_policy": "creator_then_two_parallel_reviews",
              "stop_policy": "both_reviewers_satisfied_or_interrupted", "annotation_ids": [a["id"] for a in annotations]}

    def guard():
        if not runner._valid(identity):
            raise JobStopped()
        if runner.store.get(original.id).revision_id != published.revision_id:
            raise DocumentError("The building changed during rendering; this job was interrupted. Start rendering from the new revision.", 409)

    def update(**fields):
        guard()
        runner._update(identity, status="running", **fields)

    try:
        update(phase="provider_setup", config=config, message="Starting one Hydrogen creator and two independent reviewers.")
        while True:
            guard()
            try:
                while len(providers) < 3:
                    provider = runner.provider_factory()
                    if any(provider is other for other in providers):
                        raise DocumentError("Rendering requires separate creator and two reviewer instances.", 503)
                    provider.reconstruction_model = config["render_model"]
                    provider.model = config["render_model"]
                    provider.request_deadline = None
                    provider.provider_calls = []
                    provider.diagnostic_stage = (lambda phase="render_proposing" if not providers else f"render_review_{len(providers)}": phase)
                    providers.append(provider)
                round_number += 1
                update(phase="render_proposing", render_round=round_number, candidate_digest=None,
                       reviewer_votes=[], message=f"Rendering round {round_number}; one creator call, then two reviews in parallel. Continues until both reviewers are satisfied or you stop it.")
                changes = {}
                proposal = propose(providers[0], working.snapshot(), review, feedback, annotations, message)
                guard()
                if isinstance(proposal, BuildingDescription):
                    if working.description is not None:
                        raise DocumentError("Existing model corrections must use identity-preserving typed patches.", 422)
                    candidate = working.snapshot()
                    candidate.description = assign_identities(candidate, normalize_views(proposal))
                    _validate_all_sources(candidate, candidate.description.model_dump(mode="json"))
                else:
                    patch = DescriptionPatch.model_validate(proposal)
                    candidate, changes = (apply_patch(working, patch, review) if review is not None
                                          else apply_enrichment(working, patch))
                # Apply attached calibration once, before building geometry. All later patches preserve it.
                applied = set(runner.jobs[identity].get("applied_measurement_ids", []))
                pending = [a for a in annotations if a["id"] not in applied and a["kind"] == "measurement" and a["space"] == "source"]
                if pending:
                    candidate = apply_measurements(candidate, pending)
                    changes = {**changes, "transform_updates": [*changes.get("transform_updates", []),
                        *({"floor_id": a["floor_id"], "reason": "Explicit user measurement"} for a in pending)]}
                candidate = runner.store.prepare(candidate)
                # Private rejected rounds are not saved ancestors. Embed the same
                # published lineage that commit will retain in the accepted bundle.
                candidate.parent_revision_id = published.revision_id
                candidate.revision_number = published.revision_number + 1
                candidate.interpretation_status = "complete"
                if not candidate.description or not candidate.description.floors:
                    raise DocumentError("No supported floor geometry exists yet; original sources remain available.", 422)
                _validate_all_sources(candidate, candidate.description.model_dump(mode="json"))
                update(phase="ifc_generation", message="Generating and reopening the candidate IFC locally.")
                runner._geometry(candidate)
                guard()
                failures = regression_findings(working, candidate, changes)
                if failures:
                    raise DocumentError("Candidate rejected: " + " ".join(failures), 422)
                digest = candidate_digest(candidate)
                update(phase="render_review_parallel", candidate_digest=digest,
                       message="Two independent Hydrogen reviewers inspect the same reopened IFC in parallel.")
                votes = parallel_reviews(providers[1:], candidate, digest, annotations, message, guard, update)
                guard()
                review = combined_review(votes)
                working = candidate
                if pending:
                    applied.update(a["id"] for a in pending)
                    update(applied_measurement_ids=sorted(applied))
                accepted = all(v.candidate_supported for v in votes)
                complete = accepted and all(v.satisfied for v in votes)
                update(issues=[issue.model_dump(mode="json") for issue in review.issues],
                       provider_calls=[{**call, "role": "creator" if i == 0 else f"reviewer_{i}", "worker": i + 1}
                                       for i, p in enumerate(providers) for call in getattr(p, "provider_calls", [])])
                if accepted:
                    with runner.lock:
                        guard()
                        published = runner._publish(identity, candidate, published.revision_id,
                                                    status="render_consensus" if complete else "preview_reviewing", review=review, config=config)
                        working = published.snapshot()
                if complete:
                    with runner.lock:
                        guard()
                        runner._update(identity, status="complete", phase="complete",
                            message="Both independent Hydrogen reviewers are satisfied with this exact generated model. Inspect sources and assumptions; this is not a guarantee of accuracy.")
                    return
                feedback = None
            except JobStopped:
                raise
            except DocumentError as error:
                if error.status == 409 and runner.store.get(original.id).revision_id != published.revision_id:
                    raise
                feedback = {"category": "candidate_validation", "message": error.message}
                # Failed initial geometry must reach the VLM preparation path instead of
                # deterministically rebuilding the same incomplete interpretation forever.
                update(phase="render_retry", reviewer_votes=[], candidate_digest=None, message="Candidate validation needs another rendering attempt. Previous usable model retained; Stop remains available.")
                if runner.events[identity].wait(1):
                    raise JobStopped()
            except Exception:
                # No exception text, source payload or credential crosses the diagnostics boundary.
                feedback = {"category": "provider_or_schema_failure", "message": "Previous call failed operationally; retry using the same originals and validated model contract."}
                update(phase="render_retry", reviewer_votes=[], candidate_digest=None, message="Rendering hit an operational error and will retry. Previous usable model retained; Stop remains available.")
                if runner.events[identity].wait(2):
                    raise JobStopped()
    except JobStopped:
        if runner.jobs[identity]["status"] != "interrupted":
            runner._update(identity, status="stopped", phase="stopped", message="Rendering interrupted. Original sources and the last usable model remain saved.")
    except DocumentError:
        runner.events[identity].set()
        runner._update(identity, status="interrupted", phase="interrupted", message="Rendering interrupted because the saved building revision changed. The current usable model remains saved.")
    finally:
        for provider in providers:
            try:
                provider.close()
            except Exception:
                pass
