"""Original drawing description -> deterministic IFC -> reopened/tessellated scene."""
from .building import BuildingDescription
from .documents import DocumentError
from .provider import ProviderError


def reconstruct_scene(document, page_number, provider):
    """The legacy page argument does not restrict all-source floor extraction."""
    try:
        description = BuildingDescription.model_validate(provider.reconstruct(document))
    except ProviderError:
        raise
    except Exception:
        raise ProviderError("The building-description request failed or returned an invalid response. No model was saved; no conclusion about source quality was made.") from None
    if not description.floors:
        raise DocumentError("No floor diagrams could be described confidently in the supplied pages. Source questions remain available.", 422)
    from .ifc_generate import generate_ifc
    from .ifc_artifact import load_artifact
    data = generate_ifc(description, document)
    restored = load_artifact(data, document.id)
    if restored is None:
        raise DocumentError("The generated IFC lost its drawing provenance; no model was saved.", 422)
    scene, _, _ = restored
    document.ifc_bytes = data
    return scene
