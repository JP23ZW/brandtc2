"""Validate DOCX packages and repair the known floating-cover-image defect."""
import io
from zipfile import ZipFile, BadZipFile
from lxml import etree

WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
WRAPS = {f"{{{WP}}}{name}" for name in ("wrapNone", "wrapSquare", "wrapTight", "wrapThrough", "wrapTopAndBottom")}


def checked_archive(content: bytes) -> ZipFile:
    if len(content) > 80 * 1024 * 1024:
        raise ValueError("Het Word-bestand mag maximaal 80 MB groot zijn.")
    archive = None
    try:
        archive = ZipFile(io.BytesIO(content))
        if len(archive.infolist()) > 5000 or sum(i.file_size for i in archive.infolist()) > 300 * 1024 * 1024:
            raise ValueError("Het uitgepakte Word-bestand is te groot.")
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Het Word-bestand bevat dubbele onderdelen.")
        if archive.testzip() or 'word/document.xml' not in archive.namelist():
            raise ValueError("Het Word-bestand is onvolledig of beschadigd.")
        return archive
    except (BadZipFile, KeyError, RuntimeError, ValueError) as exc:
        if archive is not None:
            archive.close()
        if isinstance(exc, ValueError):
            raise
        raise ValueError("Dit is geen leesbaar DOCX-bestand.") from exc


def repair_cover_anchors(content: bytes) -> tuple[bytes, int]:
    """Preserve all ZIP members; add only missing required anchor wrapping."""
    output = io.BytesIO()
    count = 0
    with checked_archive(content) as source, ZipFile(output, 'w') as target:
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename.startswith('word/') and member.filename.endswith('.xml'):
                root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                changed = False
                for anchor in root.iter(f"{{{WP}}}anchor"):
                    if not any(child.tag in WRAPS for child in anchor):
                        docpr = anchor.find(f"{{{WP}}}docPr")
                        if docpr is None:
                            raise ValueError("Afbeeldingsanker zonder eigenschappen in Word-bestand.")
                        anchor.insert(anchor.index(docpr), etree.Element(f"{{{WP}}}wrapNone"))
                        count += 1
                        changed = True
                if changed:
                    data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            target.writestr(member, data)
    return (output.getvalue() if count else content), count


def validate_drawing_anchors(content: bytes) -> None:
    with checked_archive(content) as archive:
        for name in archive.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                root = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
                for anchor in root.iter(f"{{{WP}}}anchor"):
                    wraps = [c for c in anchor if c.tag in WRAPS]
                    props = anchor.find(f"{{{WP}}}docPr")
                    if len(wraps) != 1 or props is None or anchor.index(wraps[0]) > anchor.index(props):
                        raise ValueError("Ongeldige positie-informatie bij een Word-afbeelding; export afgebroken.")
