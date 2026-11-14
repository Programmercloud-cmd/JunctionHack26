"""Exercise verified zero counts through the public IFC direct path."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from VQA.api import count_objects
from VQA.couting_tasks.models import gemini


class IFCZeroTests(unittest.TestCase):
    def test_direct_zero_requires_a_valid_empty_query(self):
        import ifcopenshell

        model = ifcopenshell.file(schema="IFC4")
        model.create_entity("IfcWallStandardCase", GlobalId=ifcopenshell.guid.new())
        model.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Level 1")
        door_type = model.create_entity("IfcDoorType", GlobalId=ifcopenshell.guid.new(), PredefinedType="DOOR")
        door = model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new())
        model.create_entity(
            "IfcRelDefinesByType", GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[door], RelatingType=door_type,
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "source.ifc"
            model.write(str(path))
            base = {"ids": [], "storey": 0, "scope_label": "", "complete": True, "reason": ""}
            for filters, status, invalid in (
                ([{"source": "class", "name": "IfcWindow"}], "ok", False),
                ([{"source": "class", "name": "IfcWall"}], "unsupported", True),
                ([{"source": "assigned_type", "name": "IfcDoorType"}], "unsupported", True),
                ([{"source": "class", "name": "IfcDoorType"}], "unsupported", False),
                ([], "unsupported", False),
            ):
                with self.subTest(filters=filters), patch.object(
                    gemini, "structured", return_value={**base, "zero_filters": filters},
                ) as request:
                    result = count_objects(path, "How many objects of the specified class are in the model?")
                    request.assert_called_once()
                    self.assertEqual(result.status, status)
                    self.assertEqual(result.invalid_evidence, invalid)
                    self.assertEqual(result.verified_zero, status == "ok")
                    if status == "ok":
                        self.assertEqual(tuple(result), (0, []))
                        self.assertEqual(result.evidence, [{"kind": "ifc_zero", "filters": filters, "storey": None}])
                    else:
                        self.assertIsNone(result.count)

            storey_id = model.by_type("IfcBuildingStorey")[0].id()
            with patch.object(gemini, "structured", return_value={
                **base, "storey": storey_id, "scope_label": "Level 1",
                "zero_filters": [{"source": "class", "name": "IfcWall"}],
            }):
                result = count_objects(path, "How many walls are on Level 1?")
                self.assertTrue(result.verified_zero)
                self.assertEqual(result.evidence[0]["storey"]["id"], storey_id)
