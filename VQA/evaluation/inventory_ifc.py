"""Round-trip a small extracted inventory through IFC properties."""

import argparse
import json
from pathlib import Path


def main():
    import ifcopenshell
    from ifcopenshell.util.element import get_pset

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("Write the IFC experiment under VQA.")
    output.mkdir(parents=True, exist_ok=True)
    objects = json.loads(args.inventory.read_text(encoding="utf-8"))[:10]
    model = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid.new
    columns = ("xmin", "ymin", "xmax", "ymax")
    for item in objects:
        element = model.create_entity(
            "IfcBuildingElementProxy", GlobalId=guid(), Name=item["type"], Tag=str(item["id"]),
        )
        properties = [
            model.create_entity("IfcPropertySingleValue", Name=name, NominalValue=model.create_entity("IfcInteger", value))
            for name, value in zip(columns, item["box"])
        ]
        pset = model.create_entity("IfcPropertySet", GlobalId=guid(), Name="RasterBounds", HasProperties=properties)
        model.create_entity(
            "IfcRelDefinesByProperties", GlobalId=guid(), RelatedObjects=[element], RelatingPropertyDefinition=pset,
        )
    ifc_path = output / "inventory.ifc"
    model.write(str(ifc_path))
    reopened = ifcopenshell.open(str(ifc_path))
    exported = []
    for element in reopened.by_type("IfcBuildingElementProxy"):
        properties = get_pset(element, "RasterBounds")
        exported.append({
            "id": int(element.Tag), "type": element.Name,
            "box": [properties[name] for name in columns],
        })
    if exported != objects:
        raise ValueError("IFC round-trip changed the inventory.")
    (output / "roundtrip.json").write_text(json.dumps(exported, indent=2), encoding="utf-8")
    print(f"Verified {len(exported)} inventory records.")


if __name__ == "__main__":
    main()
