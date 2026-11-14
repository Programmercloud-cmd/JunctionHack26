"""Legacy model-directed IFC lookup used for historical evaluation."""

import json
from collections import defaultdict

from .._ifc import read_occurrences, resolve_scope
from .._result import CountResult, INTEGER, TEXT, UnsupportedCount, array_schema, object_schema
from ..models import gemini


FILTER = object_schema(source={"type": "string", "enum": ["class", "assigned_type"]}, name=TEXT)
LOOKUP = object_schema(filters=array_schema(FILTER), storey=INTEGER, scope_label=TEXT, reason=TEXT)


def count_ifc_lookup(path, question):
    import ifcopenshell

    model, storeys, occurrences = read_occurrences(path)
    declarations = ifcopenshell.schema_by_name(model.schema_identifier)
    class_index = defaultdict(set)
    type_index = defaultdict(set)
    ancestors = {}
    for identifier, record in occurrences.items():
        for name, index, root in (
            (record["class"], class_index, "IfcProduct"),
            (record["assigned_type"], type_index, "IfcTypeObject"),
        ):
            if not name:
                continue
            if name not in ancestors:
                declaration = declarations.declaration_by_name(name)
                lineage = []
                while declaration is not None and declaration.name() != root:
                    lineage.append(declaration.name())
                    declaration = declaration.supertype()
                ancestors[name] = lineage
            for ancestor_class in ancestors[name]:
                index[ancestor_class].add(identifier)
    data = {"storeys": list(storeys.values())}
    serialized_question = json.dumps(question, ensure_ascii=False)
    data["present_classes_including_supertypes"] = sorted(class_index)
    data["present_assigned_type_classes"] = sorted(type_index)
    prompt = (
        "Translate the counting question to a union of exact IFC occurrence class or assigned-type "
        "filters and at most one storey ID. Class filters include all subtypes. Use 0 only for "
        "whole-model questions. Copy the storey label verbatim into scope_label and use the empty string only for whole-model questions. If a named storey is absent or ambiguous, or if the question needs "
        "criteria beyond the available filters, return no filters and explain. You may select "
        "an appropriate schema class or assigned-type class absent from the lists if the model "
        "contains none. Do not estimate a count.\n"
        f"Schema: {model.schema_identifier}\nQuestion: {serialized_question}\n"
        f"Catalog: {json.dumps(data, ensure_ascii=False)}"
    )
    reply = gemini.structured(prompt, LOOKUP)
    if not reply["filters"]:
        raise UnsupportedCount(reply["reason"] or "No supported IFC lookup was proposed.")
    ids = set()
    for query in reply["filters"]:
        source, name = query["source"], query["name"]
        try:
            declaration = declarations.declaration_by_name(name).as_entity()
        except RuntimeError as error:
            raise UnsupportedCount(f"Unknown IFC class {name!r}.") from error
        base = "IfcTypeObject" if source == "assigned_type" else "IfcProduct"
        if source not in {"class", "assigned_type"} or declaration is None or declaration.name() == base:
            raise UnsupportedCount("The proposed IFC filter is not specific enough.")
        parent = declaration.supertype()
        while parent is not None and parent.name() != base:
            parent = parent.supertype()
        if parent is None:
            raise UnsupportedCount("The proposed IFC filter is not an occurrence or assigned-type class.")
        index = type_index if source == "assigned_type" else class_index
        ids.update(index.get(declaration.name(), ()))
    storey = reply["storey"]
    resolve_scope(question, storey, reply["scope_label"], storeys)
    scoped_ids = {
        identifier for identifier in ids
        if storey == 0 or (occurrences[identifier]["storey"] or {}).get("id") == storey
    }
    evidence = [{"kind": "ifc_lookup", "filters": reply["filters"], "storey": storeys.get(storey)}]
    evidence.extend(occurrences[identifier] for identifier in sorted(scoped_ids))
    return CountResult(count=len(scoped_ids), evidence=evidence, verified_zero=not scoped_ids)
