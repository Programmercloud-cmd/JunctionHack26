# Implementation and acceptance

Accepted by planner and independent plan reviewer before implementation, 2026-11-15. Shared wire contract: [AGENTIC_CHAT_CONTRACT.md](AGENTIC_CHAT_CONTRACT.md).

1. Create isolated `feat/agentic-chat` from `origin/bugfix-linus`, preserving the dirty existing checkout.
2. Backend implementer owns coordinator/provider/direct technical service and their tests. One tool router, exact message, no Decisions preflight, shared UI delegation, document-free conversation.
3. Frontend implementer owns static UI/viewer and browser tests. Preserve Linus design; use `/api/chat`, show job/stop progress, add source/model marking and composer attachments.
4. Orchestrator owns routes, authorization, persistent annotations, independent unbounded render loop, integration, environment and documentation. No dependency additions.
5. Independent read-only implementation reviewer checks changed behavior, reproduces blockers, and rechecks fixes. Orchestrator verifies integrated flow and runs relevant/full deterministic suites and browser acceptance.

Acceptance: normal chat without sources; basic/advanced technical original-source QA and grounded refusals without `gate`/intent rewrite; conversation and both technical workers share UI actions; both independent Hydrogen reviews approve the exact same reopened model before completion; repeated/no-op/invalid/provider failures continue until agreement or interruption; in-flight Stop prevents publication; drawing/model anchors retain their coordinates through view changes; user measurements reach generation through attributed calibration; public edit restrictions remain enforced before effects. Preserve original uploads and usable revisions through operational failures/restart.

Latest user-directed rendering update: retain three calls per valid round and run the two reviews concurrently after creation/IFC validation. Use a fixed creator and two separate reviewer clients. Verify true overlap with barriers (including intercepted production SDK requests), identical/private candidate inputs, both-vote publication, out-of-order partial progress, operational retry without overlapping provider reuse, and Stop during creation/review. The no-round/cost-cap policy, preview publication requirements and original-source authority remain unchanged. Live speedup is unmeasured; expected round latency follows creation plus the slower review rather than their sum. This side-conversation update uses no sub-agents.

No new framework, provider fallback, cloud service, raster rendering, account system, source-image mutation, or annotation-to-portable-IFC extension. Existing physical geometry validators may reject a proposal but continue the render loop. New structural CAD editing is not inferred from a model-space annotation.
