"""Original drawing description -> deterministic IFC -> reopened/tessellated scene."""
from .building import BuildingDescription
from .documents import DocumentError
from .reconstruction_errors import reconstruction_error


def reconstruct_scene(document, page_number, provider):
    """The legacy page argument does not restrict all-source floor extraction."""
    try:
        output = provider.reconstruct(document)
    except Exception as error:
        raise reconstruction_error(error, "provider") from None
    try:
        description = BuildingDescription.model_validate(output)
        if not description.floors:
            raise DocumentError("No floor diagrams could be described confidently in the supplied pages. Source questions remain available.", 422)
    except Exception as error:
        raise reconstruction_error(error, "description") from None
    from .ifc_generate import generate_ifc
    from .ifc_artifact import load_artifact
    try:
        data = generate_ifc(description, document)
    except Exception as error:
        raise reconstruction_error(error, "generation") from None
    try:
        restored = load_artifact(data, document.id)
        if restored is None:
            raise DocumentError("The generated IFC lost its drawing provenance; no model was saved.", 422)
        scene, _, _ = restored
    except Exception as error:
        raise reconstruction_error(error, "artifact") from None
    document.ifc_bytes = data
    return scene
