"""Read GIMP (.xcf) files and flatten them to one image, without GIMP.

Pure Python + Pillow (numpy only for floating-point files), no Streamlit.
`flatten(data)` returns the picture GIMP would show: visible layers, bottom to
top, with opacity, offsets, layer masks and the common blend modes.

Checked against GIMP 2.10's own output (see tests/test_xcf_tools.py): legacy
modes are mixed in ordinary (gamma) space with Pillow, GIMP 2.10's modes in
linear light with numpy, one strip of rows at a time to keep memory flat.
A group that is not pass-through is drawn from the picture of itself that GIMP
saves in the file, so whatever is inside it is always exact.

Approximate, and reported in the result so the UI can say so: blend modes
other than the ones in `_BLEND` are drawn as Normal.

Format reference: GIMP's devel-docs/xcf.txt.
"""
import struct
import zlib

TILE = 64
MAX_PIXELS = 24_000_000          # canvas (or one layer) above this is refused: ~17 bytes per pixel at peak

# image / layer property ids
_PROP_END, _PROP_COLORMAP, _PROP_OPACITY, _PROP_MODE, _PROP_VISIBLE = 0, 1, 6, 7, 8
_PROP_APPLY_MASK, _PROP_OFFSETS, _PROP_COMPRESSION, _PROP_RESOLUTION = 11, 15, 17, 19
_PROP_GROUP_ITEM, _PROP_ITEM_PATH, _PROP_FLOAT_OPACITY = 29, 30, 33

_NORMAL_MODES = {0, 28}
_STRIP_ROWS = 256                 # rows per numpy strip (fewer for wide images, see _linear_draw)
_PASS_THROUGH = 61
# mode number -> name of the blend (legacy and GIMP 2.10 numbers)
_BLEND = {3: 'multiply', 30: 'multiply', 4: 'screen', 31: 'screen',
          6: 'difference', 32: 'difference', 7: 'add', 33: 'add',
          8: 'subtract', 34: 'subtract', 9: 'darker', 35: 'darker',
          10: 'lighter', 36: 'lighter', 5: 'overlay', 23: 'overlay',
          18: 'hard_light', 44: 'hard_light', 19: 'soft_light', 45: 'soft_light'}

_MODE_NAMES = {1: 'Dissolve', 11: 'Hue', 12: 'Saturation', 13: 'Color', 14: 'Value', 15: 'Divide',
               16: 'Dodge', 17: 'Burn', 20: 'Grain extract', 21: 'Grain merge', 22: 'Color erase',
               24: 'LCh Hue', 25: 'LCh Chroma', 26: 'LCh Color', 27: 'LCh Lightness', 37: 'Hue',
               38: 'Saturation', 39: 'Color', 40: 'Value', 41: 'Divide', 42: 'Dodge', 43: 'Burn',
               46: 'Grain extract', 47: 'Grain merge', 48: 'Vivid light', 49: 'Pin light',
               50: 'Linear light', 51: 'Hard mix', 52: 'Exclusion', 53: 'Linear burn',
               54: 'Luma darken only', 55: 'Luma lighten only', 56: 'Luminance', 57: 'Color erase',
               58: 'Erase', 59: 'Merge', 60: 'Split'}

# GIMP 2.10 mode -> (blend in linear light, mix in linear light); found by comparing
# against GIMP's own output for every combination
# (soft light, 45, matches GIMP when drawn the legacy way, so it is not listed)
_NEW_MODE_SPACES = {30: (True, True), 31: (False, True), 32: (False, True), 33: (True, True),
                    34: (True, True), 35: (True, True), 36: (True, True), 44: (False, True),
                    23: (False, True)}

_CHANNELS = {0: 3, 1: 4, 2: 1, 3: 2, 4: 1, 5: 2}      # layer type -> channels


class XcfError(Exception):
    """The file is not a GIMP file this reader can open (message is user-facing)."""


def is_xcf(data):
    return bytes(data[:9]) == b'gimp xcf '


class _Reader:
    def __init__(self, data):
        self.d = data
        tag = bytes(data[9:13])
        if not is_xcf(data):
            raise XcfError("This is not a GIMP file.")
        if tag == b'file':
            self.version = 0
        elif tag[:1] == b'v' and tag[1:].isdigit():
            self.version = int(tag[1:])
        else:
            raise XcfError("This GIMP file has an unknown version.")
        self.psize = 8 if self.version >= 11 else 4

    def u32(self, pos):
        return struct.unpack_from('>I', self.d, pos)[0]

    def i32(self, pos):
        return struct.unpack_from('>i', self.d, pos)[0]

    def f32(self, pos):
        return struct.unpack_from('>f', self.d, pos)[0]

    def ptr(self, pos):
        if self.psize == 8:
            return struct.unpack_from('>Q', self.d, pos)[0], pos + 8
        return struct.unpack_from('>I', self.d, pos)[0], pos + 4

    def ptr_list(self, pos):
        out = []
        while True:
            p, pos = self.ptr(pos)
            if p == 0:
                return out, pos
            out.append(p)
            if len(out) > 100_000:
                raise XcfError("This GIMP file is damaged.")

    def string(self, pos):
        n = self.u32(pos)
        pos += 4
        raw = bytes(self.d[pos:pos + max(0, n - 1)])
        return raw.decode('utf-8', errors='replace'), pos + n

    def props(self, pos):
        """{prop id: payload offset, ...} plus sizes; returns (dict, position after PROP_END)."""
        found = {}
        for _ in range(10_000):
            kind, size = self.u32(pos), self.u32(pos + 4)
            pos += 8
            if kind == _PROP_END:
                return found, pos
            found[kind] = (pos, size)
            pos += size
        raise XcfError("This GIMP file is damaged.")


def _sample_format(version, precision):
    """(bytes per sample, is_float, is_linear_light)."""
    if version < 4:
        return 1, False, False
    if version == 4:
        table = {0: (1, False, False), 1: (2, False, False), 2: (4, False, True),
                 3: (2, True, True), 4: (4, True, True)}
    else:
        size = {1: (1, False), 2: (2, False), 3: (4, False), 5: (2, True), 6: (4, True), 7: (8, True)}
        entry = size.get(precision // 100)
        table = {precision: entry + (precision % 100 == 0,)} if entry else {}
    if precision not in table:
        raise XcfError("This GIMP file uses a color depth ArtCheck cannot read.")
    return table[precision]


def _rle_plane(d, pos, count):
    """One run-length-encoded byte plane of `count` bytes; returns (bytes, new position)."""
    out = bytearray()
    while len(out) < count:
        op = d[pos]
        pos += 1
        if op <= 126:
            out += d[pos:pos + 1] * (op + 1)
            pos += 1
        elif op == 127:
            n = (d[pos] << 8) | d[pos + 1]
            out += d[pos + 2:pos + 3] * n
            pos += 3
        elif op == 128:
            n = (d[pos] << 8) | d[pos + 1]
            out += d[pos + 2:pos + 2 + n]
            pos += 2 + n
        else:
            n = 256 - op
            out += d[pos:pos + n]
            pos += n
    if len(out) != count:
        out = out[:count]
    return bytes(out), pos


def _to_8bit_planes(planes, channels, bps, is_float):
    """Reduce big-endian sample byte planes to one 8-bit plane per channel."""
    if bps == 1:
        return planes
    if not is_float:
        return [planes[c * bps] for c in range(channels)]          # most significant byte
    import numpy as np
    out = []
    kind = {2: '>f2', 4: '>f4', 8: '>f8'}[bps]
    for c in range(channels):
        raw = np.frombuffer(b''.join(planes[c * bps:(c + 1) * bps]), dtype=np.uint8)
        values = np.ascontiguousarray(raw.reshape(bps, -1).T).view(kind).reshape(-1)
        values = np.nan_to_num(values.astype(np.float32), nan=0.0, posinf=1.0, neginf=0.0)
        out.append((np.clip(values, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).tobytes())
    return out


def _tile_planes(reader, pos, tw, th, channels, bps, is_float, compression):
    """One tile as a list of 8-bit planes, one per channel."""
    d = reader.d
    count = tw * th
    bpp = channels * bps
    if compression == 1:
        planes = []
        for _ in range(bpp):
            plane, pos = _rle_plane(d, pos, count)
            planes.append(plane)
    else:
        if compression == 0:
            raw = bytes(d[pos:pos + count * bpp])
        elif compression == 2:
            raw = zlib.decompressobj().decompress(bytes(d[pos:pos + count * bpp * 2 + 1024]))
        else:
            raise XcfError("This GIMP file uses a compression ArtCheck cannot read.")
        if len(raw) < count * bpp:
            raise XcfError("This GIMP file is damaged.")
        planes = [raw[i:count * bpp:bpp] for i in range(bpp)]
    return _to_8bit_planes(planes, channels, bps, is_float)


def _read_hierarchy(reader, pos, channels, bps, is_float, compression, max_pixels):
    """A layer's or mask's pixels as a list of 'L' images, one per channel."""
    from PIL import Image
    width, height, bpp = reader.u32(pos), reader.u32(pos + 4), reader.u32(pos + 8)
    if bpp != channels * bps:
        # a layer can be stored at another depth than the image says; trust the layer
        if bpp % channels or bpp // channels not in (1, 2, 4, 8):
            raise XcfError("This GIMP file is damaged.")
        if bpp // channels == 1 or not is_float or bpp // channels == 8:
            is_float = is_float and bpp // channels != 1
        bps = bpp // channels
    if width == 0 or height == 0 or width * height > max_pixels:
        raise XcfError("This GIMP file is too large to preview.")
    level, _ = reader.ptr(pos + 12)
    tiles, _ = reader.ptr_list(level + 8)
    bands = [Image.new('L', (width, height), 0) for _ in range(channels)]
    cols = (width + TILE - 1) // TILE
    for index, tile_pos in enumerate(tiles):
        tx, ty = (index % cols) * TILE, (index // cols) * TILE
        if ty >= height:
            break
        tw, th = min(TILE, width - tx), min(TILE, height - ty)
        planes = _tile_planes(reader, tile_pos, tw, th, channels, bps, is_float, compression)
        for band, plane in zip(bands, planes):
            band.paste(Image.frombytes('L', (tw, th), plane), (tx, ty))
    return bands


_SRGB_LUT = None


def _srgb_lut():
    global _SRGB_LUT
    if _SRGB_LUT is None:
        lut = []
        for i in range(256):
            v = i / 255.0
            v = 12.92 * v if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
            lut.append(int(round(max(0.0, min(1.0, v)) * 255)))
        _SRGB_LUT = lut
    return _SRGB_LUT


def _layer_rgba(reader, layer, image, max_pixels):
    """A layer as an RGBA image (its own size), mask and opacity already applied."""
    from PIL import Image, ImageChops
    channels = _CHANNELS[layer['type']]
    bands = _read_hierarchy(reader, layer['hierarchy'], channels, image['bps'], image['is_float'],
                            image['compression'], max_pixels)
    has_alpha = layer['type'] in (1, 3, 5)
    alpha = bands[-1] if has_alpha else Image.new('L', bands[0].size, 255)
    color = bands[:-1] if has_alpha else bands
    if layer['type'] in (4, 5):                                   # indexed
        palette = image['colormap'] or bytes(range(256)) * 3
        indexed = color[0].copy()
        indexed.putpalette(bytes(palette) + bytes(768 - len(palette)))
        indexed = Image.frombytes('P', indexed.size, indexed.tobytes())
        indexed.putpalette(bytes(palette) + bytes(768 - len(palette)))
        r, g, b = indexed.convert('RGB').split()
    elif len(color) == 1:                                         # gray
        r = g = b = color[0]
    else:
        r, g, b = color
    if image['linear'] and layer['type'] not in (4, 5):
        lut = _srgb_lut()
        r, g, b = r.point(lut), g.point(lut), b.point(lut)
    if layer['mask'] and layer['apply_mask']:
        mask = _read_hierarchy(reader, _mask_hierarchy(reader, layer['mask']), 1, image['bps'],
                               image['is_float'], image['compression'], max_pixels)[0]
        if mask.size == alpha.size:
            alpha = ImageChops.multiply(alpha, mask)
    if layer['opacity'] < 255:
        opacity = layer['opacity']
        alpha = alpha.point([(i * opacity + 127) // 255 for i in range(256)])
    return Image.merge('RGBA', (r, g, b, alpha))


def _mask_hierarchy(reader, pos):
    """Pointer to the pixel hierarchy of a channel (layer mask) structure."""
    pos += 8                                   # width, height
    _, pos = reader.string(pos)
    _, pos = reader.props(pos)
    hierarchy, _ = reader.ptr(pos)
    return hierarchy


def _blend(name, below, above):
    from PIL import ImageChops
    if name == 'multiply':
        return ImageChops.multiply(below, above)
    if name == 'screen':
        return ImageChops.screen(below, above)
    if name == 'difference':
        return ImageChops.difference(below, above)
    if name == 'add':
        return ImageChops.add(below, above)
    if name == 'subtract':
        return ImageChops.subtract(below, above)
    if name == 'darker':
        return ImageChops.darker(below, above)
    if name == 'lighter':
        return ImageChops.lighter(below, above)
    if name == 'overlay':
        return ImageChops.overlay(below, above)
    if name == 'hard_light':
        return ImageChops.hard_light(below, above)
    if name == 'soft_light':
        return ImageChops.soft_light(below, above)
    return above


def _legacy_draw(canvas, art, box, blend):
    """GIMP's legacy modes: everything in ordinary (gamma) space."""
    from PIL import Image
    left, top, right, bottom = box
    if blend is None:
        canvas.alpha_composite(art, dest=(left, top))
        return
    below = canvas.crop(box)
    below_rgb, art_rgb = below.convert('RGB'), art.convert('RGB')
    mixed = Image.composite(_blend(blend, below_rgb, art_rgb), below_rgb, art.getchannel('A'))
    mixed.putalpha(below.getchannel('A'))                  # these modes never add coverage
    canvas.paste(mixed, (left, top))


_LINEAR_TABLES = None


def _linear_tables():
    """(8-bit sRGB -> linear float32, 12-bit linear -> 8-bit sRGB)."""
    global _LINEAR_TABLES
    if _LINEAR_TABLES is None:
        import numpy as np
        v = np.arange(256, dtype=np.float32) / 255.0
        to_linear = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)
        x = np.arange(4096, dtype=np.float32) / 4095.0
        enc = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
        to_srgb = np.clip(enc * 255.0 + 0.5, 0, 255).astype(np.uint8)
        _LINEAR_TABLES = (to_linear, to_srgb)
    return _LINEAR_TABLES


def _hard_light(b, a):
    import numpy as np
    return np.where(a > 0.5, 1.0 - (1.0 - b) * (1.0 - (2.0 * a - 1.0)), b * 2.0 * a)


def _linear_blend(name, b, a):
    import numpy as np
    if name == 'multiply':
        return b * a
    if name == 'screen':
        return 1.0 - (1.0 - b) * (1.0 - a)
    if name == 'difference':
        return np.abs(b - a)
    if name == 'add':
        return b + a
    if name == 'subtract':
        return b - a
    if name == 'darker':
        return np.minimum(b, a)
    if name == 'lighter':
        return np.maximum(b, a)
    if name == 'hard_light':
        return _hard_light(b, a)
    if name == 'overlay':
        return _hard_light(a, b)
    return a


def _linear_draw(canvas, art, box, blend, blend_linear=True, composite_linear=True):
    """GIMP 2.10's modes. Each mode has its own rule for whether the blend and the
    final mix happen in linear light or in ordinary (perceptual) values."""
    import numpy as np
    from PIL import Image
    to_linear, to_srgb = _linear_tables()
    left, top, right, bottom = box
    strip = max(16, min(_STRIP_ROWS, 400_000 // max(1, right - left)))   # about 400,000 pixels at a time
    for y in range(0, bottom - top, strip):
        rows = min(strip, bottom - top - y)
        strip_box = (left, top + y, right, top + y + rows)
        src = np.asarray(art.crop((0, y, right - left, y + rows)))
        if not src[..., 3].any():
            continue
        dst = np.asarray(canvas.crop(strip_box))
        sa = src[..., 3:4].astype(np.float32) / 255.0
        da = dst[..., 3:4].astype(np.float32) / 255.0
        sp, dp = src[..., :3].astype(np.float32) / 255.0, dst[..., :3].astype(np.float32) / 255.0
        sc, dc = to_linear[src[..., :3]], to_linear[dst[..., :3]]
        if blend is None:                                   # Normal: source over
            oa = sa + da * (1.0 - sa)
            oc = (sc * sa + dc * da * (1.0 - sa)) / np.maximum(oa, 1e-6)
            out_linear = True
        else:                                               # the others never add coverage
            oa = da
            mixed = _linear_blend(blend, dc, sc) if blend_linear else _linear_blend(blend, dp, sp)
            if blend_linear != composite_linear:            # move the blend result to the mixing space
                mixed = np.clip(mixed, 0.0, 1.0)
                if composite_linear:
                    mixed = to_linear[(mixed * 255.0 + 0.5).astype(np.uint8)]
                else:
                    mixed = to_srgb[(mixed * 4095.0 + 0.5).astype(np.uint16)].astype(np.float32) / 255.0
            base = dc if composite_linear else dp
            oc = mixed * sa + base * (1.0 - sa)
            out_linear = composite_linear
        out = np.empty(dst.shape, dtype=np.uint8)
        if out_linear:
            out[..., :3] = to_srgb[(np.clip(oc, 0.0, 1.0) * 4095.0 + 0.5).astype(np.uint16)]
        else:
            out[..., :3] = (np.clip(oc, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        out[..., 3:4] = np.clip(oa * 255.0 + 0.5, 0, 255).astype(np.uint8)
        # keep hidden colors of untouched pixels exactly as they were
        untouched = (src[..., 3] == 0)
        out[untouched] = dst[untouched]
        canvas.paste(Image.fromarray(out, 'RGBA'), strip_box[:2])


def _parse(data):
    reader = _Reader(data)
    pos = 14
    width, height, base_type = reader.u32(pos), reader.u32(pos + 4), reader.u32(pos + 8)
    pos += 12
    precision = 150
    if reader.version >= 4:
        precision = reader.u32(pos)
        pos += 4
    bps, is_float, linear = _sample_format(reader.version, precision)
    props, pos = reader.props(pos)
    image = {'width': width, 'height': height, 'base_type': base_type, 'version': reader.version,
             'bps': bps, 'is_float': is_float, 'linear': linear, 'bits': bps * 8,
             'compression': 0, 'colormap': None, 'dpi': None}
    if _PROP_COMPRESSION in props:
        image['compression'] = reader.d[props[_PROP_COMPRESSION][0]]
    if _PROP_COLORMAP in props:
        at, _ = props[_PROP_COLORMAP]
        n = reader.u32(at)
        image['colormap'] = bytes(reader.d[at + 4:at + 4 + 3 * min(n, 256)])
    if _PROP_RESOLUTION in props:
        at, _ = props[_PROP_RESOLUTION]
        x, y = reader.f32(at), reader.f32(at + 4)
        if 1 <= x <= 20000 and 1 <= y <= 20000:
            image['dpi'] = (x, y)
    layer_ptrs, _ = reader.ptr_list(pos)

    layers = []
    for lp in layer_ptrs:
        lw, lh, ltype = reader.u32(lp), reader.u32(lp + 4), reader.u32(lp + 8)
        name, at = reader.string(lp + 12)
        lprops, at = reader.props(at)
        hierarchy, at = reader.ptr(at)
        mask, at = reader.ptr(at)
        if ltype not in _CHANNELS:
            raise XcfError("This GIMP file is damaged.")
        layer = {'name': name, 'width': lw, 'height': lh, 'type': ltype, 'hierarchy': hierarchy,
                 'mask': mask, 'opacity': 255, 'visible': True, 'mode': 0, 'x': 0, 'y': 0,
                 'apply_mask': False, 'group': _PROP_GROUP_ITEM in lprops, 'path': None}
        if _PROP_OPACITY in lprops:
            layer['opacity'] = min(255, reader.u32(lprops[_PROP_OPACITY][0]))
        if _PROP_FLOAT_OPACITY in lprops:
            layer['opacity'] = int(round(max(0.0, min(1.0, reader.f32(lprops[_PROP_FLOAT_OPACITY][0]))) * 255))
        if _PROP_VISIBLE in lprops:
            layer['visible'] = reader.u32(lprops[_PROP_VISIBLE][0]) != 0
        if _PROP_MODE in lprops:
            layer['mode'] = reader.u32(lprops[_PROP_MODE][0])
        if _PROP_APPLY_MASK in lprops:
            layer['apply_mask'] = reader.u32(lprops[_PROP_APPLY_MASK][0]) != 0
        if _PROP_OFFSETS in lprops:
            at = lprops[_PROP_OFFSETS][0]
            layer['x'], layer['y'] = reader.i32(at), reader.i32(at + 4)
        if _PROP_ITEM_PATH in lprops:
            at, size = lprops[_PROP_ITEM_PATH]
            layer['path'] = tuple(reader.u32(at + 4 * i) for i in range(size // 4))
        layers.append(layer)
    return reader, image, layers


def describe(data):
    """Size, layer count and resolution without decoding any pixels."""
    _, image, layers = _parse(data)
    return {'width': image['width'], 'height': image['height'], 'dpi': image['dpi'],
            'layers': sum(1 for l in layers if not l['group']), 'bits': image['bits'],
            'version': image['version']}


def flatten(data, max_pixels=MAX_PIXELS):
    """Flatten a GIMP file.

    Returns {'image': RGBA PIL image, 'width', 'height', 'dpi': (x, y) or None,
             'layers': drawn layer count, 'hidden': hidden layer count, 'bits',
             'approximate': [names of blend modes drawn as Normal]}.
    Raises XcfError with a message that can be shown to the user.
    """
    from PIL import Image
    try:
        reader, image, layers = _parse(data)
        width, height = image['width'], image['height']
        if width == 0 or height == 0:
            raise XcfError("This GIMP file is empty.")
        if width * height > max_pixels:
            raise XcfError(f"This GIMP file is {width} × {height} px, too large to preview here.")

        # Where each layer sits in the layer tree. Top-level layers carry no path in
        # the file; their position is their index among the top-level layers.
        top_index = 0
        for layer in layers:
            if not layer['path'] or len(layer['path']) == 1:
                layer['path'] = (top_index,)
                top_index += 1
        by_path = {l['path']: l for l in layers}

        def parents(layer):
            path = layer['path'][:-1]
            while path:
                parent = by_path.get(path)
                if parent is not None:
                    yield parent
                path = path[:-1]

        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        drawn = hidden = 0
        approximate = []
        for layer in reversed(layers):                     # file order is top to bottom
            ancestors = list(parents(layer))
            # A normal group is drawn from GIMP's saved picture of it, so its
            # contents are skipped. A pass-through group has no picture of its
            # own: its layers are drawn straight onto what is below.
            if any(p['mode'] != _PASS_THROUGH for p in ancestors):
                if not layer['group'] and not layer['visible']:
                    hidden += 1
                continue
            if layer['group'] and layer['mode'] == _PASS_THROUGH:
                if layer['mask'] and layer['apply_mask']:
                    approximate.append('mask on a pass-through group')
                continue
            if not layer['visible'] or any(not p['visible'] for p in ancestors):
                if not layer['group']:
                    hidden += 1
                continue
            opacity = layer['opacity']
            for parent in ancestors:                       # pass-through parents only
                opacity = (opacity * parent['opacity'] + 127) // 255
            layer = dict(layer, opacity=opacity)
            if opacity == 0 or layer['width'] == 0 or layer['height'] == 0 or not layer['hierarchy']:
                continue
            # part of the layer that falls on the canvas
            left, top = max(0, layer['x']), max(0, layer['y'])
            right = min(width, layer['x'] + layer['width'])
            bottom = min(height, layer['y'] + layer['height'])
            if right <= left or bottom <= top:
                continue
            art = _layer_rgba(reader, layer, image, max_pixels)
            if (right - left, bottom - top) != art.size:
                art = art.crop((left - layer['x'], top - layer['y'], right - layer['x'], bottom - layer['y']))
            drawn += 1
            mode = layer['mode']
            blend = _BLEND.get(mode)
            if blend is None and mode not in _NORMAL_MODES:
                approximate.append(_MODE_NAMES.get(mode, f"blend mode {mode}"))
            spaces = _NEW_MODE_SPACES.get(mode)
            if mode < 23 or (spaces is None and mode != 28):
                _legacy_draw(canvas, art, (left, top, right, bottom), blend)
            else:
                _linear_draw(canvas, art, (left, top, right, bottom), blend, *(spaces or (True, True)))
            del art
        return {'image': canvas, 'width': width, 'height': height, 'dpi': image['dpi'],
                'layers': drawn, 'hidden': hidden, 'bits': image['bits'],
                'approximate': sorted(set(approximate))}
    except XcfError:
        raise
    except (struct.error, IndexError, zlib.error, ValueError, MemoryError, OverflowError) as err:
        raise XcfError("This GIMP file could not be read (it may be damaged or from an unsupported GIMP version).") from err
