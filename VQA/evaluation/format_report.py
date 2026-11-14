"""Render local PDF overlays and source evidence for the format comparison."""

import json
from base64 import b64encode
from html import escape
from pathlib import Path
from urllib.parse import quote


def write_report(path, rows, summary):
    import pymupdf

    images = {}
    sections = []
    for row in rows:
        panels = []
        visual_zero = next((item for item in row["evidence"] if item["kind"] == "pdf_visual_zero"), None)
        outcome = {"unsupported": "Unsupported", "failed": "Failed"}.get(row["status"], "Counted")
        if row["status"] == "ok" and row["count"] == 0:
            outcome = "Verified zero" if row["verified_zero"] else "Visual zero" if visual_zero else "Unverified zero"
        notes = ([row["detail"]] if row.get("detail") else []) + row.get("gaps", [])
        if visual_zero:
            pages = ", ".join(str(page) for page in visual_zero["pages"])
            notes.insert(0, f"Inspected pages {pages}. {visual_zero['reason']}")
        if row["format"] == "pdf":
            page_boxes = {page: [] for page in visual_zero["pages"]} if visual_zero else {}
            for record in row["evidence"]:
                if record.get("box"):
                    page_boxes.setdefault(record["page"], []).append(record["box"])
            for page_number, boxes in sorted(page_boxes.items()):
                key = (row["path"], page_number)
                if key not in images:
                    with pymupdf.open(row["path"]) as document:
                        page = document[page_number - 1]
                        image = page.get_pixmap(dpi=72, alpha=False)
                        images[key] = (page.rect.width, page.rect.height, b64encode(image.tobytes("jpeg")).decode())
                width, height, data = images[key]
                markup = [f"<figure><figcaption>Page {page_number}</figcaption>",
                          f'<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" style="aspect-ratio:{width / height}">',
                          f'<image width="1000" height="1000" preserveAspectRatio="none" href="data:image/jpeg;base64,{data}"/>']
                for x0, y0, x1, y1 in boxes:
                    markup.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}"/>')
                panels.append("".join(markup) + "</svg></figure>")
        sections.append(
            f"<section><h2>{escape(row['harness'])} · row {row['id']}</h2>"
            f"<p>{escape(row['question'])}</p>"
            f"<p>{outcome} · {row['count'] if row['count'] is not None else 'No count'} · {row['seconds']:.2f} s · "
            f'<a href="file://{quote(str(Path(row["path"]).resolve()))}">Open source</a></p>'
            + "".join(f"<p>{escape(note)}</p>" for note in notes) +
            f'<div class="pages">{"".join(panels)}</div><details><summary>Source evidence</summary>'
            f'<pre>{escape(json.dumps(row["evidence"], indent=2, ensure_ascii=False))}</pre></details></section>'
        )
    headings = (
        "Harness", "Cases", "Exact", "Failures", "Unsupported", "Verified zeros",
        "Visual zeros", "Median seconds", "Complete evidence", "Invalid attempts", "Eligible",
    )
    keys = (
        "harness", "cases", "exact", "failures", "unsupported", "verified_zeros",
        "visual_zeros", "median_seconds", "evidence_complete", "invalid_evidence_attempts", "eligible",
    )
    scores = "".join(
        "<tr>" + "".join(f"<td>{item[key]}</td>" for key in keys) + "</tr>"
        for scores in summary.values() for item in scores
    )
    table = "<table><tr>" + "".join(f"<th>{h}</th>" for h in headings) + f"</tr>{scores}</table>" if scores else ""
    path.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Counting format evaluation</title>'
        '<style>body{font:16px system-ui;margin:2rem;color:#17212b}td,th{padding:.4rem .8rem;text-align:left}'
        'section{border-top:1px solid #bbb}figure{margin:0;max-width:760px}pre{white-space:pre-wrap}'
        'svg{display:block;width:100%;height:auto}rect{fill:none;stroke:#d60057;stroke-width:2;vector-effect:non-scaling-stroke}'
        '.pages{display:flex;flex-wrap:wrap;gap:1rem}</style>'
        "<h1>Counting format evaluation</h1>" + table + "".join(sections) + "</html>", encoding="utf-8",
    )
