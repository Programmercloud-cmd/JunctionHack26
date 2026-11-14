"""Bounded upload normalization; source pixels are never served by filename."""
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import uuid
import warnings
from .scene import Scene

from PIL import Image, ImageOps, UnidentifiedImageError
import pypdfium2 as pdfium

MAX_UPLOAD = 10 * 1024 * 1024
MAX_IFC_UPLOAD = 25 * 1024 * 1024
MAX_PAGES = 5
MAX_PIXELS = 40_000_000
MAX_EDGE = 4096
MAX_DOCUMENTS = 20


class DocumentError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


@dataclass
class Page:
    number: int
    width: int
    height: int
    path: Path

    def image(self):
        with Image.open(self.path) as image:
            return image.copy()


@dataclass
class Document:
    id: str
    filename: str
    pages: list[Page]
    warnings: list[str] = field(default_factory=list)
    kind: str = "drawing"
    scene: Scene | None = None
    scene_lock: threading.Lock = field(default_factory=threading.Lock)
    ifc_bytes: bytes | None = None

    def public(self):
        return {
            "document_id": self.id,
            "filename": self.filename,
            "kind": self.kind,
            "scene_url": f"/api/documents/{self.id}/scene" if self.scene else None,
            "ifc_url": f"/api/documents/{self.id}/model.ifc" if self.ifc_bytes else None,
            "pages": [{"page": p.number, "width": p.width, "height": p.height,
                       "image_url": f"/api/documents/{self.id}/pages/{p.number}"} for p in self.pages],
            "warnings": self.warnings,
        }


def normalize(image: Image.Image) -> Image.Image:
    if image.width * image.height > MAX_PIXELS:
        raise DocumentError("Image exceeds the 40 megapixel limit.", 413)
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        result = Image.new("RGB", image.size, "white")
        result.paste(rgba, mask=rgba.getchannel("A"))
    else:
        result = image.convert("RGB")
    result.thumbnail((MAX_EDGE, MAX_EDGE))
    return result


class DocumentStore:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="session-", dir=root)
        self.root = Path(self.temp.name)
        self.documents: dict[str, Document] = {}
        self.lock = threading.Lock()

    def close(self):
        self.temp.cleanup()

    def get(self, document_id: str) -> Document:
        try:
            return self.documents[document_id]
        except KeyError:
            raise DocumentError("Document not found. Upload the plan again.", 404) from None

    def add(self, data: bytes, filename: str) -> Document:
        if not data:
            raise DocumentError("Choose a non-empty JPG, PNG or PDF file.")
        is_ifc = data.lstrip().startswith(b"ISO-10303-21;")
        if len(data) > (MAX_IFC_UPLOAD if is_ifc else MAX_UPLOAD):
            raise DocumentError("Upload exceeds the limit (drawings 10 MiB; IFC 25 MiB).", 413)
        with self.lock:
            if len(self.documents) >= MAX_DOCUMENTS:
                raise DocumentError("This local session has 20 documents. Restart the server to clear them.", 429)
            if is_ifc:
                from .ifc_import import import_ifc
                from .ifc_artifact import load_artifact
                document_id = uuid.uuid4().hex
                artifact = load_artifact(data, document_id)
                if artifact:
                    scene, restored, manifest = artifact
                    directory = self.root / document_id
                    directory.mkdir()
                    pages = []
                    for page, png in restored:
                        path = directory / f"{page.number}.png"
                        path.write_bytes(png)
                        pages.append(Page(page.number, page.width, page.height, path))
                    safe_name = Path(filename.replace("\\", "/")).name[:200] or "Derived building.ifc"
                    document = Document(document_id, safe_name, pages, scene.warnings,
                                        kind="drawing", scene=scene, ifc_bytes=data)
                    self.documents[document_id] = document
                    return document
                scene = import_ifc(data, document_id)
                safe_name = Path(filename.replace("\\", "/")).name[:200] or "Building.ifc"
                document = Document(document_id, safe_name, [], scene.warnings, kind="ifc", scene=scene)
                self.documents[document_id] = document
                return document
            return self._add(data, filename)

    def _add(self, data: bytes, filename: str) -> Document:
        images, notes = [], []
        try:
            if data.startswith(b"%PDF-"):
                with pdfium.PdfDocument(data) as pdf:
                    if not 1 <= len(pdf) <= MAX_PAGES:
                        raise DocumentError("PDF must contain 1–5 pages; larger documents are not silently truncated.", 413)
                    for number in range(len(pdf)):
                        page = pdf[number]
                        try:
                            width, height = page.get_size()
                            if width <= 0 or height <= 0:
                                raise DocumentError("PDF contains an invalid page.")
                            scale = min(2.0, MAX_EDGE / max(width, height))
                            bitmap = page.render(scale=scale)
                            try:
                                images.append(normalize(bitmap.to_pil()))
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
                notes.append("PDF pages were rendered as images; fine annotations may need closer inspection.")
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(data)) as image:
                        if image.format not in ("JPEG", "PNG"):
                            raise DocumentError("Only JPG, PNG and PDF files are supported.", 415)
                        if getattr(image, "n_frames", 1) != 1:
                            raise DocumentError("Animated images are not supported.", 415)
                        if max(image.size) > MAX_EDGE:
                            notes.append("Image resized to a maximum edge of 4096 pixels.")
                        images.append(normalize(image))
        except DocumentError:
            raise
        except (Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise DocumentError("Image exceeds the decoded pixel limit.", 413) from None
        except Exception:
            raise DocumentError("Could not read this file. Use a valid, unencrypted JPG, PNG or PDF.") from None
        document_id = uuid.uuid4().hex
        directory = self.root / document_id
        directory.mkdir()
        pages = []
        try:
            for number, image in enumerate(images, start=1):
                path = directory / f"{number}.png"
                image.save(path, format="PNG")
                pages.append(Page(number, image.width, image.height, path))
        finally:
            for image in images:
                image.close()
        safe_name = Path(filename.replace("\\", "/")).name[:200] or "Untitled plan"
        document = Document(document_id, safe_name, pages, notes)
        self.documents[document_id] = document
        return document
