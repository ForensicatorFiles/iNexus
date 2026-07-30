"""
Decodes a SQLite "record" — the payload format used by every table-leaf
cell (and index cell). Format: https://www.sqlite.org/fileformat2.html#record_format

    varint  header_length        (includes the size of this varint itself)
    varint  serial_type[0]        one per column, in table-declaration order
    varint  serial_type[1]
    ...
    <header_length total bytes>
    value[0]                      widths/encodings implied by each serial type
    value[1]
    ...

Serial type → storage:
    0        NULL                  0 bytes
    1        int8                  1 byte,  signed
    2        int16                 2 bytes, signed, big-endian
    3        int24                 3 bytes, signed, big-endian
    4        int32                 4 bytes, signed, big-endian
    5        int48                 6 bytes, signed, big-endian
    6        int64                 8 bytes, signed, big-endian
    7        float64               8 bytes, IEEE-754, big-endian
    8        integer constant 0    0 bytes
    9        integer constant 1    0 bytes
    10, 11   reserved (internal use — never appears in a real record)
    N >= 12, even   BLOB, length (N-12)/2
    N >= 13, odd    TEXT, length (N-13)/2, in the header's text encoding
"""
import struct

from .varint import read_varint


def _signed_int(raw):
    """Big-endian two's-complement signed int of whatever width `raw` is."""
    val = int.from_bytes(raw, "big", signed=False)
    bits = len(raw) * 8
    if val >= (1 << (bits - 1)):
        val -= (1 << bits)
    return val


def decode_record(payload, text_encoding="utf-8"):
    """
    Returns a list of Python values (None/int/float/str/bytes), one per
    column, in table-declaration order. Raises ValueError if the payload
    doesn't parse as a well-formed record — the caller (btree.py) treats
    that as "this isn't actually a residual row here, skip it."
    """
    header_len, pos = read_varint(payload, 0)
    if header_len < 1 or header_len > len(payload):
        raise ValueError("implausible record header length")

    serial_types = []
    header_end = header_len
    while pos < header_end:
        st, pos = read_varint(payload, pos)
        serial_types.append(st)
    if pos != header_end:
        raise ValueError("record header did not end exactly where its own length said it would")

    values = []
    data_pos = header_end
    for st in serial_types:
        if st == 0:
            values.append(None)
        elif st == 1:
            values.append(_signed_int(payload[data_pos:data_pos + 1])); data_pos += 1
        elif st == 2:
            values.append(_signed_int(payload[data_pos:data_pos + 2])); data_pos += 2
        elif st == 3:
            values.append(_signed_int(payload[data_pos:data_pos + 3])); data_pos += 3
        elif st == 4:
            values.append(_signed_int(payload[data_pos:data_pos + 4])); data_pos += 4
        elif st == 5:
            values.append(_signed_int(payload[data_pos:data_pos + 6])); data_pos += 6
        elif st == 6:
            values.append(_signed_int(payload[data_pos:data_pos + 8])); data_pos += 8
        elif st == 7:
            if data_pos + 8 > len(payload):
                raise ValueError("float64 value runs past end of payload")
            values.append(struct.unpack(">d", payload[data_pos:data_pos + 8])[0]); data_pos += 8
        elif st == 8:
            values.append(0)
        elif st == 9:
            values.append(1)
        elif st in (10, 11):
            raise ValueError(f"serial type {st} is reserved/internal — not a real record")
        elif st >= 12 and st % 2 == 0:
            length = (st - 12) // 2
            if data_pos + length > len(payload):
                raise ValueError("BLOB value runs past end of payload")
            values.append(bytes(payload[data_pos:data_pos + length])); data_pos += length
        elif st >= 13:
            length = (st - 13) // 2
            if data_pos + length > len(payload):
                raise ValueError("TEXT value runs past end of payload")
            raw = bytes(payload[data_pos:data_pos + length])
            try:
                values.append(raw.decode(text_encoding, errors="strict"))
            except UnicodeDecodeError:
                raise ValueError("TEXT value is not valid text in the DB's declared encoding")
            data_pos += length
        else:
            raise ValueError(f"impossible serial type {st}")

    return values
