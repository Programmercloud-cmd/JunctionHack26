# Faithful spoken answers

Speech is prepared from the final validated answer, after deterministic calculation replacement. No additional model call rewrites or summarizes it. The written `answer`, evidence arrays, highlights and displayed missing-information/proposal fields are unchanged.

## Presentation contract

`Answer.spoken_answer` is the default version; `spoken_answer_with_details` is the explicit full-detail option. Both preserve ordinary prose, useful measurements and uncertainty. The same narrow formatting applies to the main text, missing-information entries and next action. They append all `missing_information` entries under “Missing or unresolved” and `next_action` under “Next step”, even when those terms already occur in the main answer. Separate proposals remain visual; qualifications already in the main answer are preserved.

The default removes narrowly recognized coordinate/bounding-box values, opaque object identifiers and citation metadata. It never removes an entire sentence or parenthetical just because it contains metadata, nor arbitrary numeric lists or bracketed numbers. Human window labels such as W1/W-01, dimensional ranges/lists, negations, approximate/unknown wording and ordinary source-scope prose are retained. If the content consists solely of removed metadata, speech directs the user to the written technical details and retains any missing-information/next-action text.

A direct positive request in the original question retains the requested category; negative requests override it for that category. Automatic request detection covers direct English phrasing. The visible “Read technical details” option provides an explicit all-category override for any language or ambiguous wording. Unrecognized prose is preserved rather than guessed away. This conservative choice can leave an unfamiliar annotation audible; new patterns need preservation tests before they are removed.

The two fields are derived presentation, not source evidence. Explicit null disables spoken preparation for that answer; the browser must not leak raw metadata through a fallback. Truly absent fields retain backward compatibility for older API responses. Changing the details option stops old playback but does not automatically spend credits on another synthesis.

The existing 6,000-character speech bound applies after preparation. Adding qualifiers can exceed it; the app keeps the written answer and reports the speech limit rather than truncating qualifications.

## Verification

Deterministic tests cover window counts, locations, dimensions, uncertainty, metadata and explicit inclusion/exclusion requests. Boundary checks verify calculation results are inserted before formatting, no extra inference calls are made, and formatting failure preserves grounded text/evidence. Browser checks compare the exact selected speech payload with the untouched written answer and visible citations/highlights. Final results: **286 integrated tests passed**, with 71 focused checks independently reviewed and a successful live window-answer playback check. See [VOICE_VERIFICATION.md](VOICE_VERIFICATION.md).

## Tested example

An injected fixture containing two windows, approximate 1.2 m widths, a bounding box, an opaque GlobalId, a citation marker and unknown heights produces:

> There are 2 windows on the north wall, each approximately 1.2 m wide. Their height is not established. Missing or unresolved: Window height. Next step: Check the section drawing.

The original fixture answer and its evidence remain byte-for-byte unchanged in the presentation test. This example is a deterministic control-flow fixture, not a claim about a real building.
