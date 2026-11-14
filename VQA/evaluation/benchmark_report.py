"""Generate a self-contained HTML comparison of counting predictions."""

from base64 import b64encode
from collections import Counter
from html import escape
from io import BytesIO
from itertools import combinations

from PIL import Image

from VQA.couting_tasks.legacy.counting_harnesses import HARNESSES


def checked_boxes(boxes):
    valid = []
    for box in boxes:
        if (isinstance(box, list) and len(box) == 4 and all(type(value) is int for value in box)
                and 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000):
            valid.append(box)
    return valid, len(boxes) - len(valid)


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (area_a + area_b - overlap)


def agreement(first, second):
    candidates = []
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            score = iou(a, b)
            if score >= 0.5:
                candidates.append((-score, i, j))
    used_first, used_second = set(), set()
    for _, i, j in sorted(candidates):
        if i not in used_first and j not in used_second:
            used_first.add(i)
            used_second.add(j)
    matched = len(used_first)
    return matched, len(first) - matched, len(second) - matched


def image_data(path):
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1800, 1800))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=88)
    return b64encode(buffer.getvalue()).decode("ascii")


def panel(name, row, boxes, invalid, image_id):
    if row is None:
        return f"<section><h3>{name}</h3><p>Missing run</p></section>"
    if "error" in row:
        markup = [f"<section><h3>{name}</h3><p>Failed: {escape(row['error'])}</p>"]
    else:
        markup = [f"<section><h3>{name}</h3><p>Predicted {row['count']}</p>"]
    if "ids" in row:
        markup.append(f"<p>Counted IDs {escape(str(row['ids']))}</p>")
    if "boxes" not in row and "error" not in row:
        markup.append("<p>No localization output</p>")
    duplicates = sum(iou(a, b) >= 0.8 for a, b in combinations(boxes, 2))
    if invalid or duplicates:
        markup.append(f"<p>{invalid} invalid boxes, {duplicates} potential duplicate pairs</p>")
    markup.append('<div class="blueprint">')
    markup.append(
        '<svg viewBox="0 0 1000 1000" preserveAspectRatio="none">'
        f'<use href="#{image_id}" width="1000" height="1000"/>'
    )
    for x0, y0, x1, y1 in boxes:
        markup.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}"/>')
    markup.append("</svg></div></section>")
    return "".join(markup)


def write_report(path, cases, results, summary):
    rows = {(row["id"], row["harness"]): row for row in results}
    images = {}
    totals = Counter()
    sections = []
    for case in cases:
        digest = case["digest"]
        image_id = f"im-{digest}"
        if digest not in images:
            with Image.open(case["image"]) as source:
                aspect = source.width / source.height
            images[digest] = (aspect, image_data(case["image"]))
        aspect, _ = images[digest]
        panels = []
        localized = {}
        for name in HARNESSES:
            row = rows.get((case["id"], name))
            boxes, invalid = checked_boxes(row.get("boxes", [])) if row else ([], 0)
            panels.append(panel(name, row, boxes, invalid, image_id))
            if row and "boxes" in row:
                localized[name] = boxes
        pair_lines = []
        predictions = {
            row["count"] for name in HARNESSES
            if (row := rows.get((case["id"], name))) and row["count"] is not None
        }
        for a, b in combinations(localized, 2):
            matched, first, second = agreement(localized[a], localized[b])
            totals[(a, b, "matches")] += matched
            totals[(a, b, "unmatched first")] += first
            totals[(a, b, "unmatched second")] += second
            same_count = rows[case["id"], a]["count"] == rows[case["id"], b]["count"]
            note = " · Same count with different localization" if same_count and (first or second) else ""
            pair_lines.append(f"<li>{a} / {b}: {matched} matched, {first} / {second} unmatched{note}</li>")
        label = " · Count disagreement" if len(predictions) > 1 else ""
        sections.append(
            f'<article id="case-{case["id"]}" style="--aspect:{aspect}"><h2>{escape(case["question"])}</h2>'
            f'<p>{case["split"]} · row {case["id"]} · Expected {case["expected"]}{label}</p>'
            f'<div class="panels">{"".join(panels)}</div><ul>{"".join(pair_lines)}</ul></article>'
        )
    definitions = "".join(
        f'<image id="im-{digest}" width="1000" height="1000" preserveAspectRatio="none" '
        f'href="data:image/jpeg;base64,{data}"/>' for digest, (_, data) in images.items()
    )
    def metric(value):
        return "—" if value is None else f"{value:,.2f}"

    scores = "".join(
        f'<tr><td>{item["harness"]}</td><td>{item["correct"]}/{item["cases"]}</td>'
        f'<td>{item["completed"]}</td><td>{item["failures_or_missing"]}</td>'
        f'<td>{metric(item["mae"])}</td><td>{metric(item["median_seconds"])}</td>'
        f'<td>{metric(item["p95_seconds"])}</td><td>{metric(item["calls_per_completed_case"])}</td>'
        f'<td>{item["reported_tokens"] if item["reported_tokens"] is not None else "—"}</td></tr>'
        for item in summary
    )
    pair_summary = "".join(
        f"<li>{a} / {b}: {n} matched, {totals[a, b, 'unmatched first']} / "
        f"{totals[a, b, 'unmatched second']} unmatched</li>"
        for (a, b, metric), n in totals.items() if metric == "matches"
    )
    path.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Counting benchmark</title>'
        '<style>body{font:16px system-ui;margin:2rem;color:#17212b}article{border-top:1px solid #ccc}'
        '.panels{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:12px;overflow:auto}'
        '.panels section{display:grid;grid-template-rows:subgrid;grid-row:span 5}'
        '.panels section h3{grid-row:1}.panels section .blueprint{grid-row:5}'
        'svg{display:block;width:100%;height:auto;aspect-ratio:var(--aspect,1)}'
        'rect{fill:none;stroke:#d60057;stroke-width:2px;vector-effect:non-scaling-stroke}'
        'td,th{text-align:left;padding:.35rem 1rem}</style>'
        f'<svg width="0" height="0" style="position:absolute;width:0;height:0"><defs>{definitions}</defs></svg>'
        '<h1>Counting benchmark</h1>'
        '<table><tr><th>Harness</th><th>Exact matches</th><th>Completed</th><th>Failures or missing</th>'
        '<th>MAE</th><th>Median seconds</th><th>P95 seconds</th><th>Calls per completed case</th>'
        f'<th>Reported tokens</th></tr>{scores}</table>'
        '<h2>Localization agreement</h2><p>Greedy one-to-one matching in descending IoU order at IoU ≥ 0.5. '
        'Equal IoUs break ties by source box order. Potential duplicates use IoU ≥ 0.8. '
        'Count accuracy uses the dataset labels.</p>'
        f'<ul>{pair_summary}</ul>{"".join(sections)}</html>',
        encoding="utf-8",
    )
