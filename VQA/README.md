# Blueprint counting

Run these commands from the directory containing `VQA`.

```bash
python -m pip install -r VQA/requirements.txt
python -m VQA.evaluation.evaluate_formats
```

Set `GEMINI_API_KEY` in the environment or the project’s local `.env`.
The API and evaluation use `gemini-4-hydrogen`. Inference sends source
content to Gemini. IFC parsing stays local. The API sends a compact catalog
of storeys and grouped STEP IDs to Gemini.

```python
from dataclasses import asdict

from VQA.api import count_objects

result = count_objects(path, "How many doors are shown?")
count, boxes = result
record = asdict(result)
```

The response carries `status`, `count`, `boxes`, `evidence`, `gaps`,
`verified_zero`, `invalid_evidence`, and `detail`. Check `status` before using the count.
Successful counts may have evidence gaps. Unsupported questions and
failed attempts have no count. A supported zero with source-backed
evidence sets `verified_zero`. The compatibility arguments `provider="gemini"`
and `model="gemini-4-hydrogen"` are optional. Other values return an unsupported result before any model call.

`VQA.api.count_objects` is the public entry point. It selects a fixed
counting path by file extension:

| Source | API counting path |
|---|---|
| PNG or JPEG | Independent recount |
| PDF | `pdf-native`, which sends the original PDF |
| IFC | `ifc-direct`, which validates Gemini's selected STEP IDs against the original IFC |

Counting implementations and the Gemini adapter live under `VQA/couting_tasks/`.
The alternative PDF and IFC harnesses and historical raster comparisons live
in `VQA/couting_tasks/legacy/` and are available to evaluation scripts.

- **PNG/JPEG.** Image boxes retain `[xmin, ymin, xmax, ymax]` coordinates
  normalized to 0–1000 on the original image, with the origin at the top
  left. The evidence identifies contributing boxes where available.
- **PDF.** Read `evidence` for one-based page numbers, original-page boxes
  in the same normalized coordinate system, and validated excerpts.
  A box is relative to the displayed page, including its rotation.
  Text citations are checked on their cited page. A box and an excerpt
  on one page may independently support the same claim. Schedule counts
  identify the quoted total or each validated subtotal used in the sum.
  Use occurrence IDs to connect repeated views. For scanned pages,
  evidence may be visual only. The native PDF path distinguishes three outcomes
  when no matching objects are found or a count cannot be established:

  | Outcome | Result | Evidence |
  |---|---|---|
  | Verified zero | `status="ok"`, `count=0`, `verified_zero=True` | A validated source citation, such as a schedule row showing zero |
  | Visual zero | `status="ok"`, `count=0`, `verified_zero=False` | A `pdf_visual_zero` record with one-based `pages` and a `reason` describing what was checked, plus a gap explaining the limits of visual inspection |
  | Unsupported | `status="unsupported"`, `count=None` | A reason, such as ambiguous symbols, incomplete coverage, or missing evidence for the claimed count |

  A visual zero requires an explicit model claim after inspecting the relevant
  areas. An empty evidence list alone never produces a count.
- **IFC.** The evidence locates source occurrences by STEP ID (the
  number after `#` in IFC text), IFC class, and GlobalId when available.
  It records names and scope information where relevant. IFC returns
  an empty 2D box list. For a zero count, Gemini supplies class or assigned-type
  filters and a scope. The direct harness verifies that the filters match no
  occurrences in that scope, then returns `count=0`, `verified_zero=True`,
  and an `ifc_zero` record. An empty ID selection without filters is
  unsupported. Verification applies to the model-interpreted filters, so
  show the filters and scope alongside the answer.

## Live API examples

These calls were run against Gemini Hydrogen. Paths are relative to the
project directory containing `VQA`. Each JSON block is the complete
`asdict(result)` output from that call. A fresh call may return different
evidence or counts.

The JPEG example uses a JPEG copy of the PNG floor plan. Create it first:

```python
from pathlib import Path

from PIL import Image

jpeg = Path("VQA/benchmark-runs/api-examples/plan.jpg")
jpeg.parent.mkdir(parents=True, exist_ok=True)
with Image.open("junction-dataset-preview/data/cubicasa5k/high_quality-11384.png") as image:
    image.convert("RGB").save(jpeg, format="JPEG", quality=95)
```

Import `asdict` and `count_objects` as shown above, then run any of these calls.

### PNG

```python
result = count_objects(
    "junction-dataset-preview/data/cubicasa5k/high_quality-11384.png",
    "How many toilet bowls (WC seats) are drawn on this floor plan?",
)
record = asdict(result)
```

```json
{
  "count": 1,
  "boxes": [
    [
      166,
      710,
      268,
      748
    ]
  ],
  "status": "ok",
  "evidence": [
    {
      "kind": "image",
      "occurrence_id": 1,
      "box": [
        166,
        710,
        268,
        748
      ]
    }
  ],
  "gaps": [],
  "verified_zero": false,
  "detail": "first pass (counts agreed)",
  "invalid_evidence": false
}
```

### JPEG

```python
result = count_objects(
    "VQA/benchmark-runs/api-examples/plan.jpg",
    "How many toilet bowls (WC seats) are drawn on this floor plan?",
)
record = asdict(result)
```

```json
{
  "count": 1,
  "boxes": [
    [
      165,
      715,
      268,
      750
    ]
  ],
  "status": "ok",
  "evidence": [
    {
      "kind": "image",
      "occurrence_id": 1,
      "box": [
        165,
        715,
        268,
        750
      ]
    }
  ],
  "gaps": [],
  "verified_zero": false,
  "detail": "first pass (counts agreed)",
  "invalid_evidence": false
}
```

### PDF

```python
result = count_objects(
    "junction-dataset/data/swiss_dwellings/site1048_bldg2155_floor9741.pdf",
    "How many rooms labelled 'Küche' are there on this floor?",
)
record = asdict(result)
```

```json
{
  "count": 1,
  "boxes": [],
  "status": "ok",
  "evidence": [
    {
      "kind": "pdf",
      "page": 1,
      "occurrence_id": "kuche_5_02",
      "box": [
        416,
        140,
        507,
        262
      ],
      "excerpt": "Küche",
      "value": null
    }
  ],
  "gaps": [],
  "verified_zero": false,
  "detail": null,
  "invalid_evidence": false
}
```

### IFC

```python
result = count_objects(
    "junction-dataset/data/ifc_models/bsc-clinic_clinic-structural.ifc",
    "How many stairs are there in the model 'Medical-Dental Clinic - structural'?",
)
record = asdict(result)
```

```json
{
  "count": 1,
  "boxes": [],
  "status": "ok",
  "evidence": [
    {
      "kind": "ifc",
      "step_id": 529,
      "global_id": "2lH_RQeBDBG8rH6PWO_5vu",
      "class": "IfcStair",
      "name": "Stair:Monolithic Concrete Stair:222487",
      "assigned_type": null,
      "type_step_id": null,
      "storey": {
        "id": 5569,
        "name": "TOF Footing",
        "long_name": null
      },
      "storey_relationship_step_ids": [
        317658
      ]
    }
  ],
  "gaps": [],
  "verified_zero": false,
  "detail": null,
  "invalid_evidence": false
}
```

## Frontend integration

Call `count_objects` on the server. Wire it into the application's question
handler using the ID of the uploaded source and the user's question. Resolve
the ID to an authorized, stored file on the server. Run the synchronous VQA
call in a worker or thread pool if the handler is async. Keep credentials
on the server.

```python
from dataclasses import asdict

from VQA.api import count_objects


def build_count_response(source_id, source_path, question):
    result = count_objects(source_path, question)
    return {"source_id": source_id, **asdict(result)}
```

This is an example response adapter for your question handler. VQA exposes a
Python function. The HTTP route, upload handling, and source URLs belong to
the host application. Use `source_id` to associate the response with the
exact source revision shown in the viewer. Discard stale responses when the
user switches sources while a request is in flight.

### Render the answer state

| Condition | GUI treatment |
|---|---|
| Request pending | Show a loading indicator and keep the source visible. |
| `status === "ok" && count > 0` | Show the count and an evidence list. |
| `status === "ok" && count === 0 && verified_zero` | Show **0 · Verified zero** and link to the source citation. |
| `status === "ok" && count === 0 && !verified_zero` | Show **0 · Visual inspection** when there is a `pdf_visual_zero` record. Show **0 · Unverified** for other unverified zeros. |
| `status === "unsupported"` | Show **Count unavailable** and the reason in `detail`, if present. |
| `status === "failed"` or the HTTP request fails | Show an error with a retry action. |

Render every `gaps` message beneath a successful answer so users can see
what the evidence does not establish. A missing count is JSON `null`.
Display `detail`, excerpts, and other source strings as plain text using
the framework's normal escaping.

### Render evidence by kind

Iterate over `result.evidence` and dispatch on `kind`. Keep any unrecognized
records out of the overlay layer. The top-level `boxes` array is a convenience
for raster images. Use `evidence` for page-aware PDFs and IFC.

| `kind` | Fields to read | GUI behavior |
|---|---|---|
| `image` | `occurrence_id`, `box` | Draw the box on the source image. Clicking an evidence row selects its box. |
| `pdf` | `page`, `occurrence_id`, `box`, `excerpt`, `value` | Open the one-based source page. Draw the box when present and show the quoted excerpt when present. Group repeated views by `occurrence_id` and keep each page link available. |
| `pdf_aggregation` | `operation`, `operands`, `count` | Show the cited total or sum. Each operands key matches the `occurrence_id` of its supporting `pdf` record. Link each operand to that record's page and excerpt. |
| `pdf_visual_zero` | `pages`, `reason` | Show the inspection explanation and links to the inspected pages. Show the page without a count overlay. |
| `ifc` | `step_id`, `global_id`, `class`, `name`, `storey` | Highlight the matching occurrence in the original IFC. Use `global_id` if indexed by the viewer, or map `step_id` to the viewer's object ID for this source. If no mesh is available, display the source reference `#<step_id>` and available metadata. |
| `ifc_zero` | `filters`, `storey` | Show the checked IFC classes or assigned types and the storey scope. A null storey means the whole model was checked. |
| `ifc_lookup` (legacy reports) | `filters`, `storey` | Show the scope used by the legacy lookup harness. Only `ifc` occurrence records are selectable objects. |

Optional evidence fields may be `null`. An IFC `storey` record, when
available, contains `id`, `name`, and `long_name`. Additional IFC fields
`assigned_type`, `type_step_id`, and `storey_relationship_step_ids` can be
shown in a details panel. Use the returned `count` as the answer. A PDF
can have multiple citations for one occurrence or a single cited total
covering multiple objects.

### Align image and PDF overlays

Place an SVG over the displayed **content** rectangle, excluding viewer
padding or letterboxing. Give it `viewBox="0 0 1000 1000"` and
`preserveAspectRatio="none"`. Keep it in the same zoom and pan container as
the image or PDF canvas. Render PDF pages with their source rotation and
filter evidence to the displayed page before drawing. If your PDF viewer
uses zero-based page indexes, convert at the viewer boundary with
`page - 1`.

```js
function boxAttributes([xmin, ymin, xmax, ymax]) {
  return { x: xmin, y: ymin, width: xmax - xmin, height: ymax - ymin };
}
```

For a canvas overlay, multiply horizontal coordinates by its content width
divided by `1000`, and vertical coordinates by its content height divided by
`1000`. See [the format report renderer](evaluation/format_report.py) for
the same SVG technique applied to original PDF pages.

## Evaluation

The no-argument format evaluation compares the public API's native PDF and
direct IFC paths with the legacy rendered PDF and model-directed IFC lookup.
It writes a manifest, incremental per-case JSONL, and a summary under
`VQA/benchmark-runs/format-evaluation-25-visual-zero/`. Use the same command
to resume. The report shows verified zeros, visual zeros, and unsupported
results separately. Visual zeros can earn exact-match credit and are flagged
as incomplete evidence. Results measured before this mode was added are
preserved under `VQA/benchmark-runs/format-evaluation-25/`.

```bash
python -m VQA.evaluation.check_repeated_views
python -m VQA.evaluation.evaluate_models
```

The first command checks both PDF paths on a separate synthetic two-page
source with the same identified door in both views. The image smoke
script uses the same public API. See [benchmark notes](evaluation/BENCHMARK.md)
for the raster harness comparison.

## Live held-out comparison

The benchmark samples PDF and IFC rows labeled `count` from the full
`questions.jsonl` without wording filters. The original split had 17
held-out IFC questions. The expanded split assigns whole sources using
residues 1 and 3 modulo 5 from the first eight digits of their SHA-256
digest. It has 16,143 development and 10,030 held-out PDF rows, and 37
development and 39 held-out IFC rows. Seed 71 selects 25 questions per
format, covering 25 PDF files and eight IFC models. Each pair of harnesses
received the same questions and files. Labels were used only for scoring.

| Harness | Exact | Failures | Median | Complete evidence |
|---|---:|---:|---:|---:|
| PDF rendered | 22/25 | 1 | 16.15 s | 24/25 |
| PDF native | 20/25 | 2 | 17.10 s | 23/25 |
| IFC lookup | 25/25 | 0 | 3.91 s | 25/25 |
| IFC direct | 25/25 | 0 | 7.64 s | 25/25 |

A harness is eligible when at least half its cases have complete evidence
and no accepted response has invalid source locators. Unsupported and failed
cases count as incorrect. Both PDF harnesses rejected one evidence-invalid
attempt. Rendered PDF had the highest PDF accuracy. IFC lookup tied on
accuracy and failures and had lower median latency. The public API uses native PDF and direct IFC by design. Latencies were measured with up to four evaluations in flight.

The dataset's PDF count questions all point to single-page files. The
separate two-page synthetic check returned one door with references on both
pages for both harnesses. Its four boxes overlapped the source-rendered
door regions at IoU ≥ 0.96. Dataset PDF overlay pages are in the HTML report.
Model interpretation still controls semantic scope, object identity across
different views, and whether a cited schedule value answers the question.
The legacy IFC lookup supports occurrence class, assigned-type class, and storey
selection. Questions requiring other predicates may be unsupported.
An empty legacy lookup verifies zero for the validated query; its relevance to the
user's wording depends on the model's interpretation. An image zero with
no source-backed evidence remains unverified.
