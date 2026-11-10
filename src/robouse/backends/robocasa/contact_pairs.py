"""Explicit, scene-versioned MJCF pairs; no inferred contact-parameter mapping."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET


def validate(spec: dict) -> list[dict]:
    """Validate the opt-in descriptor without loading a simulator or assets."""
    if "contact_pairs_v1" not in spec:
        return []
    value = spec["contact_pairs_v1"]
    if not isinstance(value, dict) or set(value) != {"version", "pairs"} or value["version"] != "1.0.0":
        raise ValueError("contact_pairs_v1 requires version 1.0.0 and pairs")
    pairs = value["pairs"]
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("contact_pairs_v1.pairs must be a nonempty list")
    names, sides = set(), set()
    fields = {"name", "geom1", "geom2", "margin", "gap", "condim", "friction", "solref", "solimp"}
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != fields:
            raise ValueError("contact_pairs_v1 pair requires every explicit MJCF parameter")
        for key in ("name", "geom1", "geom2"):
            if not isinstance(pair[key], str) or not pair[key].strip():
                raise ValueError(f"contact_pairs_v1.{key} must be a nonempty name")
        side = frozenset((pair["geom1"], pair["geom2"]))
        if len(side) != 2 or side in sides or pair["name"] in names:
            raise ValueError("contact_pairs_v1 duplicate name, pair or self-pair")
        names.add(pair["name"])
        sides.add(side)
        if type(pair["condim"]) is not int or pair["condim"] not in (1, 3, 4, 6):
            raise ValueError("contact_pairs_v1.condim must be 1, 3, 4 or 6")
        for key, count in (("margin", 1), ("gap", 1), ("friction", 5), ("solref", 2), ("solimp", 5)):
            raw = pair[key]
            values = [raw] if count == 1 else raw
            if (
                not isinstance(values, list)
                or len(values) != count
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in values)
            ):
                raise ValueError(f"contact_pairs_v1.{key} requires {count} finite numbers")
            if key in ("margin", "gap", "friction") and any(x < 0 for x in values):
                raise ValueError(f"contact_pairs_v1.{key} must be nonnegative")
    return pairs


def add(model, spec: dict) -> None:
    """Append explicit pairs after object assembly, rejecting missing/duplicate geoms."""
    pairs = validate(spec)
    if not pairs:
        return
    geoms = {g.get("name") for g in model.worldbody.iter("geom")}
    existing_names = {p.get("name") for p in model.contact}
    existing_sides = {frozenset((p.get("geom1"), p.get("geom2"))) for p in model.contact.findall("pair")}
    # Validate the complete request before mutating the assembled model.
    for pair in pairs:
        if pair["geom1"] not in geoms or pair["geom2"] not in geoms:
            raise ValueError(f"contact_pairs_v1 unknown assembled geom in {pair['name']}")
        if pair["name"] in existing_names or frozenset((pair["geom1"], pair["geom2"])) in existing_sides:
            raise ValueError(f"contact_pairs_v1 conflicts with existing contact: {pair['name']}")
    for pair in pairs:
        attrs = {k: " ".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in pair.items()}
        ET.SubElement(model.contact, "pair", attrs)
