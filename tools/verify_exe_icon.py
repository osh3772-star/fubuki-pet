"""Verify every Windows icon resource against the approved multi-size ICO."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct


def read_ico(path: Path) -> list[tuple[bytes, bytes]]:
    data = path.read_bytes()
    if len(data) < 6:
        raise ValueError('Invalid ICO header')
    reserved, kind, count = struct.unpack_from('<HHH', data)
    if reserved != 0 or kind != 1 or count == 0 or len(data) < 6 + 16 * count:
        raise ValueError('Invalid ICO directory')
    images = []
    for index in range(count):
        offset = 6 + 16 * index
        metadata = data[offset:offset+12]
        length, start = struct.unpack_from('<II', data, offset+8)
        if start < 6+16*count or start+length > len(data) or length == 0:
            raise ValueError('Invalid ICO image range')
        images.append((metadata, data[start:start+length]))
    return images


def verify(exe: Path, ico: Path) -> dict:
    # pefile is a PyInstaller build dependency; no application runtime dependency.
    import pefile
    expected = read_ico(ico)
    pe = pefile.PE(str(exe))
    try:
        kinds = {entry.id: entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
        if 3 not in kinds or 14 not in kinds:
            raise ValueError('Executable is missing Windows icon resources')
        payloads = {}
        for entry in kinds[3].directory.entries:
            info = entry.directory.entries[0].data.struct
            payloads[entry.id] = pe.get_data(info.OffsetToData, info.Size)
        for group in kinds[14].directory.entries:
            info = group.directory.entries[0].data.struct
            data = pe.get_data(info.OffsetToData, info.Size)
            if len(data) < 6 or struct.unpack_from('<HHH', data) != (0, 1, len(expected)):
                continue
            matched = True
            for index, (metadata, payload) in enumerate(expected):
                offset = 6 + index*14
                if len(data) < offset+14:
                    matched = False; break
                resource_id = struct.unpack_from('<H', data, offset+12)[0]
                if data[offset:offset+12] != metadata or payloads.get(resource_id) != payload:
                    matched = False; break
            if matched:
                return {'verified': True, 'images': len(expected),
                        'sizes': [[m[0] or 256, m[1] or 256] for m, _ in expected],
                        'source_sha256': hashlib.sha256(ico.read_bytes()).hexdigest()}
        raise ValueError('Executable icon resources do not match the approved ICO')
    finally:
        pe.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('ico', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.exe, args.ico), indent=2))
