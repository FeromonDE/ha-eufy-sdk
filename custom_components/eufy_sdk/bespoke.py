"""
Bespoke handling for known properties the generic classifier can't model well.

Some properties are packed values (`kind: "bitfield"`) that mean nothing as a single
number. When we know the layout we describe it here and the platforms build friendlier
entities (one switch per bit) instead of the generic fallback. Anything not listed
degrades to a read-only diagnostic sensor — add an entry to give a param real controls.
"""

from __future__ import annotations

# Bitfield properties we know how to split into per-bit switches.
#   {property_name: {"base": <bits always kept set>, "bits": {entity_label: bit_mask}}}
# `base` is OR'd into every write (e.g. aiDetectType's 0x30000 "AI detection enabled"
# flag), so toggling one class never clears enable. Labels become the entity names.
BITFIELD_SWITCHES: dict[str, dict] = {
    "aiDetectType": {
        "base": 0x30000,
        "bits": {
            "Detect human": 0x2,
            "Detect vehicle": 0x4,
            "Detect pet": 0x8,
            "Face recognition": 0x1,
        },
    },
}
