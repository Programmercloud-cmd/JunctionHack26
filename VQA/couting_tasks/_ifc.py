"""Select and verify counts from original IFC occurrence relationships."""

import json
import re
import unicodedata
from collections import defaultdict

from ._result import CountResult, INTEGER, TEXT, InvalidEvidence, UnsupportedCount, array_schema, object_schema
from .models import gemini


ZERO_FILTER = object_schema(source={"type": "string", "enum": ["class", "assigned_type"]}, name=TEXT)
DIRECT = object_schema(
    ids=array_schema(INTEGER), storey=INTEGER, scope_label=TEXT,
    complete={"type": "boolean"}, reason=TEXT, zero_filters=array_schema(ZERO_FILTER),
)


def storey_membership(entity):
    visited = set()
    relationships = []
    while entity is not None and entity.id() not in visited:
        if entity.is_a("IfcBuildingStorey"):
            return entity.id(), relationships
        visited.add(entity.id())
        containment = getattr(entity, "ContainedInStructure", ())
        if containment:
            relationship = containment[0]
            entity = relationship.RelatingStructure
        else:
            candidates = (*getattr(entity, "Decomposes", ()), *getattr(entity, "Nests", ()))
            relationship = next(
                (item for item in candidates if item.is_a("IfcRelAggregates") or item.is_a("IfcRelNests")),
                None,
            )
            entity = relationship.RelatingObject if relationship is not None else None
        if relationship is not None:
            relationships.append(relationship.id())
    return 0, []


def name_key(value):
    return " ".join(unicodedata.normalize("NFC", value or "").casefold().split())


def resolve_scope(question, returned_storey, scope_label, storeys):
    if type(returned_storey) is not int or (returned_storey != 0 and returned_storey not in storeys):
        raise InvalidEvidence("The proposed storey does not resolve to an IFC storey.")
    label = name_key(scope_label)
    normalized_question = name_key(question)
    if label and not re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", normalized_question):
        raise InvalidEvidence("The proposed scope label is absent from the question.")
    quoted = {name_key(match) for match in re.findall(r"""['"‘“„]([^'"’“”]+)['"’“”]""", question)}
    candidates = set()
    for identifier, storey in storeys.items():
        names = {name_key(storey["name"]), name_key(storey["long_name"])} - {""}
        named = names.intersection({label} if label else quoted)
        if named or (not label and any(
            re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", normalized_question)
            for name in names
        )):
            candidates.add(identifier)
    if len(candidates) > 1:
        raise UnsupportedCount("The explicitly named IFC storey is ambiguous.")
    if label and not candidates:
        raise UnsupportedCount("The explicitly named IFC storey does not exist.")
    if returned_storey and not label:
        raise InvalidEvidence("A scoped IFC count must quote the requested storey label.")
    if candidates != ({returned_storey} if returned_storey else set()):
        raise InvalidEvidence("The proposed storey does not match the question's scope.")


def reject_derived(model):
    if (
        any(item.Name == "Pset_BlueprintQA" for item in model.by_type("IfcPropertySet"))
        or any("BlueprintQA::DrawingDerived" in (item.Description or "") for item in model.by_type("IfcProject"))
        or any(item.Name == "UNSCALED_DISPLAY_UNIT" for item in model.by_type("IfcContextDependentUnit"))
    ):
        raise UnsupportedCount("Use the original drawing source for drawing-derived IFC.")


def read_occurrences(path):
    import ifcopenshell
    from ifcopenshell.util.element import get_aggregate, get_nest, get_type

    model = ifcopenshell.open(path)
    reject_derived(model)
    storeys = {
        item.id(): {"id": item.id(), "name": item.Name, "long_name": item.LongName}
        for item in model.by_type("IfcBuildingStorey")
    }
    occurrences = {}
    for item in model.by_type("IfcProduct"):
        # Stair flights and modeled sub-stairs belong to the enclosing stair assembly.
        if item.is_a("IfcStair"):
            visited = {item.id()}
            parent = get_aggregate(item) or get_nest(item)
            while parent is not None and parent.id() not in visited and not parent.is_a("IfcStair"):
                visited.add(parent.id())
                parent = get_aggregate(parent) or get_nest(parent)
            if parent is not None and parent.id() not in visited:
                continue
        assigned = get_type(item)
        storey, relationships = storey_membership(item)
        cls = item.is_a()
        assigned_class = assigned.is_a() if assigned is not None else ""
        identifier = item.id()
        occurrences[identifier] = {
            "kind": "ifc", "step_id": identifier, "global_id": item.GlobalId,
            "class": cls, "name": item.Name, "assigned_type": assigned_class or None,
            "type_step_id": assigned.id() if assigned is not None else None,
            "storey": storeys.get(storey),
            "storey_relationship_step_ids": relationships,
        }
    return model, storeys, occurrences


def verify_zero(model, occurrences, storey, filters):
    import ifcopenshell

    if not filters:
        raise UnsupportedCount("An empty selection needs a class or assigned-type filter to verify zero.")
    schema = ifcopenshell.schema_by_name(model.schema_identifier)
    scoped = [
        record for record in occurrences.values()
        if storey == 0 or (record["storey"] or {}).get("id") == storey
    ]
    for query in filters:
        source, name = query["source"], query["name"]
        root = {"class": "IfcProduct", "assigned_type": "IfcTypeObject"}.get(source)
        try:
            declaration = schema.declaration_by_name(name).as_entity()
        except RuntimeError as error:
            raise UnsupportedCount(f"Unknown IFC class {name!r}.") from error
        parent = declaration.supertype() if declaration is not None else None
        while parent is not None and parent.name() != root:
            parent = parent.supertype()
        if parent is None:
            raise UnsupportedCount("The proposed zero filter is not an occurrence or assigned-type class.")
        field = "step_id" if source == "class" else "type_step_id"
        if any(record[field] and model.by_id(record[field]).is_a(declaration.name()) for record in scoped):
            raise InvalidEvidence("The proposed zero filter matches IFC occurrences in the requested scope.")


def count_ifc_direct(path, question):
    model, storeys, occurrences = read_occurrences(path)
    groups = defaultdict(list)
    for identifier, record in occurrences.items():
        storey = (record["storey"] or {}).get("id", 0)
        groups[record["class"], record["assigned_type"] or "", storey].append(identifier)
    data = {"storeys": list(storeys.values())}
    serialized_question = json.dumps(question, ensure_ascii=False)
    data["groups"] = [
        {"class": cls, "assigned_type": assigned, "storey": storey, "ids": ids}
        for (cls, assigned, storey), ids in groups.items()
    ]
    prompt = (
        "Select every matching STEP occurrence ID from the complete catalog. "
        "Each group lists every member ID exactly once. Use storey 0 for whole-model questions "
        "and the exact catalog storey ID for a storey-restricted question. Copy the storey label verbatim into scope_label; use the empty string only for a whole-model question. "
        "For a positive count, return the selected IDs and leave zero_filters empty. "
        "For zero, return no IDs and provide the IFC occurrence class or assigned-type class "
        "filters that express the requested target, including classes absent from the catalog. "
        "Python will check the union of those filters, including subtypes, within the requested scope. "
        "Set complete false if the catalog cannot establish the count or if the zero filters "
        "cannot express the requested target. "
        f"\nSchema: {model.schema_identifier}\nQuestion: {serialized_question}"
        f"\nCatalog: {json.dumps(data, ensure_ascii=False)}"
    )
    reply = gemini.structured(prompt, DIRECT)
    if reply["complete"] is not True:
        raise UnsupportedCount(reply["reason"] or "No complete occurrence selection.")
    if any(type(identifier) is not int or identifier not in occurrences for identifier in reply["ids"]):
        raise InvalidEvidence("A proposed STEP ID does not resolve to an IFC occurrence.")
    ids = set(reply["ids"])
    storey = reply["storey"]
    resolve_scope(question, storey, reply["scope_label"], storeys)
    if not ids:
        filters = reply.get("zero_filters", [])
        verify_zero(model, occurrences, storey, filters)
        return CountResult(count=0, verified_zero=True, evidence=[{
            "kind": "ifc_zero", "filters": filters, "storey": storeys.get(storey),
        }])
    scoped_ids = {
        identifier for identifier in ids
        if storey == 0 or (occurrences[identifier]["storey"] or {}).get("id") == storey
    }
    if ids != scoped_ids:
        raise InvalidEvidence("A proposed occurrence lies outside the selected storey.")
    return CountResult(count=len(ids), evidence=[occurrences[identifier] for identifier in sorted(ids)])
