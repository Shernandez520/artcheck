"""Pull the small page preview that InDesign saves inside an .indd file.

InDesign documents cannot be rendered without InDesign, but by default it stores
a JPEG thumbnail of the first page in the document's XMP metadata
(`xmp:Thumbnails` / `xmpGImg:image`, base64). That thumbnail is all this reads.
Pure Python + Pillow, no Streamlit.

Details that matter (checked on real files from InDesign CC):
- An .indd holds many XMP packets: one per placed image (written by Photoshop or
  Illustrator, with their own thumbnails) and several generations of the
  document's own. Only packets whose CreatorTool is InDesign count, and of those
  the most recently saved one.
- The base64 text is broken up with `&#xA;` line breaks.
"""
import base64
import io
import re

INDD_MAGIC = bytes.fromhex('0606edf5d81d46e5bd31efe7fe74b71d')

_PACKET = re.compile(rb'<\?xpacket begin.*?<\?xpacket end', re.S)
_IMAGE = re.compile(rb'<xmpGImg:image>(.*?)</xmpGImg:image>', re.S)
_CREATOR = re.compile(rb'<xmp:CreatorTool>([^<]*)</xmp:CreatorTool>')
_SAVED = re.compile(rb'<xmp:MetadataDate>([^<]*)</xmp:MetadataDate>')


def is_indd(data):
    return bytes(data[:16]) == INDD_MAGIC


def _decode(raw):
    """base64 text from the XMP -> a verified JPEG/PNG as (bytes, (width, height)) or None."""
    from PIL import Image
    text = re.sub(rb'&#x[0-9A-Fa-f]+;|[^A-Za-z0-9+/]', b'', raw)     # also drops '=' padding
    if len(text) % 4 == 1:
        text = text[:-1]
    text += b'=' * (-len(text) % 4)
    try:
        blob = base64.b64decode(text)
        with Image.open(io.BytesIO(blob)) as img:
            img.load()
            if img.format not in ('JPEG', 'PNG') or min(img.size) < 8:
                return None
            return blob, img.size
    except Exception:
        return None


def thumbnail(data):
    """The saved first-page preview of an InDesign document.

    Returns {'image': bytes (JPEG or PNG), 'width', 'height', 'app': 'Adobe InDesign ...',
             'saved': 'YYYY-MM-DD'} or None when the file has no usable preview.
    """
    if not is_indd(data):
        return None
    found = []
    for packet in _PACKET.finditer(data):
        text = packet.group(0)
        creator = _CREATOR.search(text)
        if not creator or b'indesign' not in creator.group(1).lower():
            continue
        images = _IMAGE.findall(text)
        if not images:
            continue
        saved = _SAVED.search(text)
        stamp = saved.group(1).decode('ascii', errors='ignore') if saved else ''
        found.append((stamp, creator.group(1).decode('utf-8', errors='replace').strip(), images))
    # Newest save first; within it page 1 first. A preview can be unreadable (the
    # file stores long metadata in pieces), so fall through to the next one.
    best = decoded = None
    for stamp, app, images in sorted(found, key=lambda item: item[0], reverse=True):
        for raw in images[:6]:
            decoded = _decode(raw)
            if decoded:
                best = (stamp, app)
                break
        if decoded:
            break
    if not decoded:
        return None
    blob, (width, height) = decoded
    return {'image': blob, 'width': width, 'height': height, 'app': best[1], 'saved': best[0][:10]}
