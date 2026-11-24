"""Byte-exact user-area transfer model for compatible NFC Forum Type 2 tags.

This is deliberately NOT UID cloning. Source and destination must have the
same advertised user-area size. RF writer independently verifies destination
chip geometry, unchanged original bytes and selected UID before writing.
"""


def checked_image(data, capacity):
    if not isinstance(data, bytes):
        raise ValueError("A raw image must contain bytes")
    if not isinstance(capacity, int) or capacity < 16 or capacity > 1008 or capacity % 4:
        raise ValueError("Unsupported Type 2 user-area size")
    if len(data) != capacity:
        raise ValueError(f"Source has {len(data)} bytes; destination needs {capacity}")
    return data


def transfer_plan(original, source):
    """Build user-page changes only; page zero is never in this address space."""
    checked_image(original, len(original))
    checked_image(source, len(original))
    return [(4 + off // 4, source[off:off+4])
            for off in range(0, len(original), 4)
            if original[off:off+4] != source[off:off+4]]


def describe_raw(image):
    if not isinstance(image, dict):
        raise ValueError("Invalid tag image")
    data = checked_image(image.get("data"), image.get("capacity"))
    return f"{len(data)} user-memory bytes from NFC-A tag {image.get('uid', 'unknown')}"
