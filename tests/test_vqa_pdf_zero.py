"""Exercise PDF count outcomes in both attachment modes."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from VQA.evaluation.format_harnesses import count_with_harness
from VQA.evaluation.format_report import write_report
from VQA.couting_tasks.models import gemini


class PDFZeroTests(unittest.TestCase):
    def setUp(self):
        try:
            import pymupdf
        except ModuleNotFoundError:
            self.skipTest("Install VQA/requirements.txt to test PDF counting.")

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "plan.pdf"
        with pymupdf.open() as document:
            document.new_page().insert_text((60, 60), "Ground floor plan")
            document.new_page().insert_text((60, 60), "Lavabos: 0")
            document.save(self.path)

    def run_harnesses(self, reply):
        for harness, mime_types in (
            ("pdf-native", ["application/pdf"]),
            ("pdf-rendered", ["image/png", "image/png"]),
        ):
            with self.subTest(harness=harness), patch.object(gemini, "structured", return_value=reply) as model:
                result = count_with_harness(self.path, "How many lavabos?", harness)
                prompt, schema, attachments = model.call_args.args
                self.assertIn("visual_zero", schema["properties"]["mode"]["enum"])
                self.assertIn("choose unsupported", prompt)
                self.assertEqual([mime for _, mime in attachments], mime_types)
                yield result

    def test_visual_zero(self):
        reply = {
            "mode": "visual_zero", "evidence": [], "inspected_pages": [1, 2],
            "reason": "Checked the plumbing fixture symbols in all rooms.",
        }
        for result in self.run_harnesses(reply):
            self.assertEqual(result.status, "ok")
            self.assertEqual(tuple(result), (0, []))
            self.assertFalse(result.verified_zero)
            self.assertIn("visual inspection", result.gaps[0])
            self.assertEqual(result.evidence, [{
                "kind": "pdf_visual_zero", "pages": [1, 2], "reason": reply["reason"],
            }])

    def test_zero_from_source_citation(self):
        reply = {
            "mode": "zero", "inspected_pages": [], "reason": "",
            "evidence": [{"page": 2, "occurrence_id": "total", "box": [], "excerpt": "Lavabos: 0", "value": 0}],
        }
        for result in self.run_harnesses(reply):
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.count, 0)
            self.assertTrue(result.verified_zero)
            self.assertEqual(result.evidence[0]["page"], 2)
            self.assertFalse(result.gaps)

    def test_unsupported(self):
        for reply in (
            {"mode": "unsupported", "reason": "Plumbing symbols overlap."},
            {"mode": "unsupported", "reason": "The relevant areas are cut off."},
            {"mode": "instances", "evidence": []},
            {},
            {"mode": "visual_zero", "inspected_pages": [], "reason": "Checked fixtures."},
            {"mode": "visual_zero", "inspected_pages": [3], "reason": "Checked fixtures."},
            {"mode": "visual_zero", "inspected_pages": [True], "reason": "Checked fixtures."},
            {"mode": "visual_zero", "inspected_pages": [1], "reason": " "},
            {"mode": "zero", "evidence": [
                {"page": 1, "occurrence_id": "total", "box": [], "excerpt": "Lavabos: 0", "value": 0},
            ]},
        ):
            with self.subTest(reply=reply):
                for result in self.run_harnesses(reply):
                    self.assertEqual(result.status, "unsupported")
                    self.assertIsNone(result.count)
                    self.assertFalse(result.verified_zero)

    def test_report_labels_outcomes(self):
        base = {
            "format": "pdf", "harness": "pdf-native", "question": "How many lavabos?",
            "path": str(self.path), "id": 1, "seconds": 0, "evidence": [],
        }
        report = self.path.with_suffix(".html")
        write_report(report, [
            {**base, "status": "ok", "count": 0, "verified_zero": True},
            {**base, "status": "ok", "count": 0, "verified_zero": False, "evidence": [
                {"kind": "pdf_visual_zero", "pages": [1], "reason": "Checked the fixture symbols."},
            ]},
            {**base, "status": "unsupported", "count": None, "detail": "Incomplete coverage."},
        ], {})
        html = report.read_text()
        for label in ("Verified zero", "Visual zero", "Unsupported", "Inspected pages 1", "Incomplete coverage."):
            self.assertIn(label, html)
