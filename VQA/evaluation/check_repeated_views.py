"""Create and evaluate a labeled two-page PDF with the same door in both views."""

from dataclasses import asdict
from pathlib import Path

from VQA.evaluation.benchmark import write_json


OUTPUT = Path(__file__).resolve().parents[1] / "benchmark-runs" / "repeated-views"
QUESTION = "How many distinct doors are shown across both views? Count each physical door once."


def create_fixture(path):
    import pymupdf

    with pymupdf.open() as document:
        for index, view in enumerate(("Ground floor plan", "Door detail"), 1):
            page = document.new_page(width=620, height=450)
            page.insert_text((40, 48), view, fontsize=21)
            page.insert_text((40, 81), "Door ID D-01, ground floor west entrance", fontsize=13)
            origin = 120 if index == 1 else 270
            page.draw_rect(pymupdf.Rect(origin, 145, origin + 130, 355), width=3)
            page.draw_circle(pymupdf.Point(origin + 106, 260), 5)
            page.insert_text((origin + 40, 389), "D-01", fontsize=16)
        document.save(path)


def main():
    from VQA.evaluation.format_harnesses import count_with_harness

    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "repeated-door.pdf"
    if not path.is_file():
        create_fixture(path)
    rows = {}
    for name in ("pdf-native", "pdf-rendered"):
        result = count_with_harness(path, QUESTION, name)
        rows[name] = asdict(result)
        print(name, result.status, result.count, flush=True)
    write_json(OUTPUT / "results.json", rows)


if __name__ == "__main__":
    main()
