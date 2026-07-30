"""
SQLite's variable-length integer encoding: 1-9 bytes, big-endian, 7 bits of
payload per byte (high bit = "more bytes follow"), except the 9th byte
(if reached) contributes all 8 of its bits. Used everywhere in the file
format — cell payload lengths, rowids, and every column's serial type.
"""


def read_varint(data, offset):
    """Returns (value, new_offset). Reads at most 9 bytes starting at offset."""
    result = 0
    for i in range(8):
        if offset + i >= len(data):
            raise ValueError("varint runs past end of buffer")
        byte = data[offset + i]
        result = (result << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            return result, offset + i + 1
    # 9th byte: all 8 bits count, no continuation bit
    if offset + 8 >= len(data):
        raise ValueError("varint runs past end of buffer")
    result = (result << 8) | data[offset + 8]
    return result, offset + 9
