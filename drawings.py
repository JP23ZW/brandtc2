"""Persistent drawing pages, touch viewer and annotated report attachments."""
from __future__ import annotations

import base64
import io
import shutil
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
import streamlit.components.v1 as components
import storage
from access_control import require_object


VIEWER = components.declare_component("triacon_drawing", path=str(Path(__file__).parent / "drawing_viewer"))
MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 30
MAX_SIDE = 3200


def data_path(relative: str) -> Path:
    root = storage.DB_PATH.parent.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Ongeldig tekeningpad.")
    return target


def import_drawing(content: bytes, filename: str, report_id: int, number: str, floor: str) -> list[int]:
    require_object('edit_report', 'report', report_id)
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Kies een bestand van maximaal 40 MB.")
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise ValueError("Gebruik een PDF-, PNG- of JPG-bestand.")
    directory = data_path(f"drawings/{report_id}/{uuid.uuid4().hex}")
    directory.mkdir(parents=True)
    try:
        original = directory / ("origineel" + extension)
        original.write_bytes(content)
        pages = []

        def save_page(image: Image.Image, page_number: int) -> None:
            image = ImageOps.exif_transpose(image).convert("RGBA")
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            path = directory / f"pagina-{page_number}.png"
            background.save(path)
            pages.append(dict(
                name=Path(filename).name, drawing_number=number.strip() or Path(filename).stem,
                floor=floor.strip(), page_number=page_number,
                original_path=str(original.relative_to(storage.DB_PATH.parent)),
                image_path=str(path.relative_to(storage.DB_PATH.parent)),
                width=background.width, height=background.height,
            ))

        if extension == ".pdf":
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(content)
            try:
                if not 1 <= len(pdf) <= MAX_PAGES:
                    raise ValueError("Een PDF mag maximaal 30 pagina’s bevatten.")
                for index in range(len(pdf)):
                    page = pdf[index]
                    try:
                        width, height = page.get_size()
                        bitmap = page.render(scale=min(3, MAX_SIDE / max(width, height)))
                        try:
                            save_page(bitmap.to_pil(), index + 1)
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
            finally:
                pdf.close()
        else:
            with Image.open(io.BytesIO(content)) as image:
                save_page(image, 1)
        return storage.insert_drawings(report_id, pages)
    except Exception:
        # Only this new UUID directory; no existing user files are touched.
        shutil.rmtree(directory)
        raise


def marker_label(marker: dict) -> str:
    return f"{marker['code_group']}.{int(marker['code_number']):02d}"


def show_drawing(drawing: dict, key: str):
    require_object('view', 'drawing', drawing['id'])
    encoded = base64.b64encode(data_path(drawing["image_path"]).read_bytes()).decode("ascii")
    markers = [dict(item, label=marker_label(item)) for item in storage.drawing_markers(drawing["id"])]
    return VIEWER(image="data:image/png;base64," + encoded, drawing_id=drawing["id"],
                  markers=markers, aspect=drawing["height"] / drawing["width"], key=key, default=None)


def annotated_image(drawing: dict) -> io.BytesIO:
    require_object('view', 'drawing', drawing['id'])
    with Image.open(data_path(drawing["image_path"])) as source:
        image = source.convert("RGB")
    painter = ImageDraw.Draw(image)
    size = max(18, round(image.width * 0.020))
    try:
        font = ImageFont.truetype("arialbd.ttf", size)
    except OSError:
        font = ImageFont.load_default(size=size)
    for marker in storage.drawing_markers(drawing["id"]):
        x, y = marker["x"] * (image.width - 1), marker["y"] * (image.height - 1)
        label = marker_label(marker)
        box = painter.textbbox((0, 0), label, font=font)
        width, height = box[2] - box[0], box[3] - box[1]
        pad = max(3, size // 6)
        left = min(max(pad, x + pad), image.width - width - pad * 2)
        top = min(max(pad, y - height - pad * 3), image.height - height - pad * 2)
        painter.line((x, y, left, top + height + pad), fill="#d71920", width=max(2, size // 12))
        painter.ellipse((x-pad, y-pad, x+pad, y+pad), fill="#d71920")
        painter.rounded_rectangle((left-pad, top-pad, left+width+pad, top+height+pad), radius=pad,
                                  fill="white", outline="#d71920", width=max(1, size // 16))
        painter.text((left, top-box[1]), label, fill="#d71920", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def report_drawings(report_id: int) -> list[dict]:
    return [dict(item, annotated=annotated_image(item)) for item in storage.list_drawings(report_id)]


def drawings_pdf(drawings: list[dict]) -> bytes:
    """Export current annotated pages, one at a time to bound memory use."""
    import pypdfium2 as pdfium
    for drawing in drawings:
        require_object('export', 'drawing', drawing['id'])
    if not drawings:
        raise ValueError("Er zijn geen tekeningen om te downloaden.")
    result = pdfium.PdfDocument.new()
    try:
        for drawing in drawings:
            with Image.open(annotated_image(drawing)) as image:
                page_bytes = io.BytesIO()
                image.convert("RGB").save(page_bytes, format="PDF", resolution=150)
            source = pdfium.PdfDocument(page_bytes.getvalue())
            try:
                result.import_pages(source)
            finally:
                source.close()
        output = io.BytesIO()
        result.save(output)
        return output.getvalue()
    finally:
        result.close()
