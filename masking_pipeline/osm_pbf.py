#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small OSM PBF reader for highway ways and admin boundary relations.

The pipeline prefers ``osmium-tool`` when it is on PATH, but this reader is
the default because the lab image does not ship osmium and ``pyosmium`` needs
a compiled libosmium. Only nodes inside a caller-supplied lon/lat window are
kept, then a second pass keeps highway ways that touch those nodes.
"""
from __future__ import annotations

import struct
import zlib
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import lzma
except ImportError:  # pragma: no cover
    lzma = None

NodeTable = Dict[int, Tuple[float, float]]
WayRecord = Tuple[int, Dict[str, str], List[int]]
# relation id, tags, outer way ids, inner way ids
BoundaryRelation = Tuple[int, Dict[str, str], List[int], List[int]]


def _varint(buf: bytes, i: int) -> Tuple[int, int]:
    shift = 0
    result = 0
    n = len(buf)
    while i < n:
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, i
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")
    raise ValueError("truncated varint")


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _signed64(n: int) -> int:
    if n >= (1 << 63):
        return n - (1 << 64)
    return n


def iter_fields(buf: bytes):
    i = 0
    n = len(buf)
    while i < n:
        key, i = _varint(buf, i)
        field_no, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
            yield field_no, wire, value
        elif wire == 1:
            if i + 8 > n:
                raise ValueError("truncated fixed64")
            yield field_no, wire, buf[i : i + 8]
            i += 8
        elif wire == 2:
            length, i = _varint(buf, i)
            if i + length > n:
                raise ValueError("truncated length-delimited field")
            yield field_no, wire, buf[i : i + length]
            i += length
        elif wire == 5:
            if i + 4 > n:
                raise ValueError("truncated fixed32")
            yield field_no, wire, buf[i : i + 4]
            i += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")


def _inflate_blob(blob: bytes) -> bytes:
    raw = None
    raw_size = None
    zlib_data = None
    lzma_data = None
    zstd_data = None
    for field_no, wire, value in iter_fields(blob):
        if field_no == 1 and wire == 2:
            raw = value
        elif field_no == 2 and wire == 0:
            raw_size = value
        elif field_no == 3 and wire == 2:
            zlib_data = value
        elif field_no == 4 and wire == 2:
            lzma_data = value
        elif field_no == 7 and wire == 2:
            zstd_data = value
    if raw is not None:
        data = raw
    elif zlib_data is not None:
        data = zlib.decompress(zlib_data)
    elif lzma_data is not None:
        if lzma is None:
            raise RuntimeError("PBF blob is lzma-compressed but lzma is unavailable")
        data = lzma.decompress(lzma_data)
    elif zstd_data is not None:
        try:
            import zstandard
        except ImportError as exc:
            raise RuntimeError(
                "PBF blob is zstd-compressed. Install the zstandard package or recompress with zlib."
            ) from exc
        data = zstandard.ZstdDecompressor().decompress(zstd_data)
    else:
        raise ValueError("OSM blob has no recognized payload")
    if raw_size is not None and len(data) != raw_size:
        raise ValueError(f"OSM blob size mismatch: header {raw_size}, inflated {len(data)}")
    return data


def iter_file_blobs(path: str) -> Iterable[Tuple[str, bytes]]:
    with open(path, "rb") as handle:
        while True:
            header_len_raw = handle.read(4)
            if not header_len_raw:
                return
            if len(header_len_raw) != 4:
                raise ValueError(f"truncated OSM PBF header length in {path}")
            header_len = struct.unpack(">I", header_len_raw)[0]
            header = handle.read(header_len)
            if len(header) != header_len:
                raise ValueError(f"truncated OSM PBF blob header in {path}")
            blob_type = None
            data_size = None
            for field_no, wire, value in iter_fields(header):
                if field_no == 1 and wire == 2:
                    blob_type = value.decode("utf-8", "replace")
                elif field_no == 3 and wire == 0:
                    data_size = value
            if blob_type is None or data_size is None:
                raise ValueError(f"OSM PBF blob header missing type or datasize in {path}")
            blob = handle.read(data_size)
            if len(blob) != data_size:
                raise ValueError(f"truncated OSM PBF blob in {path}")
            yield blob_type, _inflate_blob(blob)


def parse_header_block(raw: bytes) -> dict:
    info: dict = {"required_features": [], "optional_features": []}
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 2:
            bbox = {}
            for bfield, bwire, bvalue in iter_fields(value):
                if bwire == 0:
                    bbox[bfield] = _zigzag(bvalue) * 1e-9
            info["bbox_lonlat"] = [
                bbox.get(1),
                bbox.get(4),
                bbox.get(2),
                bbox.get(3),
            ]
        elif field_no == 4 and wire == 2:
            info["required_features"].append(value.decode("utf-8", "replace"))
        elif field_no == 5 and wire == 2:
            info["optional_features"].append(value.decode("utf-8", "replace"))
        elif field_no == 16 and wire == 2:
            info["writingprogram"] = value.decode("utf-8", "replace")
        elif field_no == 17 and wire == 2:
            info["source"] = value.decode("utf-8", "replace")
        elif field_no == 22 and wire == 0:
            info["osmosis_replication_timestamp"] = _signed64(value)
        elif field_no == 23 and wire == 0:
            info["osmosis_replication_sequence_number"] = _signed64(value)
        elif field_no == 24 and wire == 2:
            info["osmosis_replication_base_url"] = value.decode("utf-8", "replace")
    return info


def _string_table(raw: bytes) -> List[str]:
    strings: List[str] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 2:
            strings.append(value.decode("utf-8", "replace"))
    if not strings:
        strings = [""]
    return strings


def _scan_block_nodes(raw: bytes, accept: Callable[[int, float, float], None]) -> None:
    granularity = 100
    lat_offset = 0
    lon_offset = 0
    groups: List[bytes] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 2 and wire == 2:
            groups.append(value)
        elif field_no == 17 and wire == 0:
            granularity = int(value)
        elif field_no == 19 and wire == 0:
            lat_offset = _signed64(value)
        elif field_no == 20 and wire == 0:
            lon_offset = _signed64(value)
    if granularity == 0:
        raise ValueError("OSM primitive block granularity is 0")
    for group in groups:
        for field_no, wire, value in iter_fields(group):
            if field_no == 2 and wire == 2:
                _consume_dense(value, granularity, lat_offset, lon_offset, accept)
            elif field_no == 1 and wire == 2:
                _consume_node(value, granularity, lat_offset, lon_offset, accept)


def _consume_dense(
    raw: bytes,
    granularity: int,
    lat_offset: int,
    lon_offset: int,
    accept: Callable[[int, float, float], None],
) -> None:
    ids = lats = lons = b""
    for field_no, wire, value in iter_fields(raw):
        if wire != 2:
            continue
        if field_no == 1:
            ids = value
        elif field_no == 8:
            lats = value
        elif field_no == 9:
            lons = value
    if not ids:
        return
    id_acc = 0
    lat_acc = 0
    lon_acc = 0
    ii = li = oi = 0
    n_ids, n_lats, n_lons = len(ids), len(lats), len(lons)
    while ii < n_ids:
        delta, ii = _varint(ids, ii)
        id_acc += _zigzag(delta)
        if li >= n_lats or oi >= n_lons:
            raise ValueError("dense nodes ended before lat/lon streams")
        dlat, li = _varint(lats, li)
        lat_acc += _zigzag(dlat)
        dlon, oi = _varint(lons, oi)
        lon_acc += _zigzag(dlon)
        lat = (lat_offset + granularity * lat_acc) * 1e-9
        lon = (lon_offset + granularity * lon_acc) * 1e-9
        accept(id_acc, lon, lat)


def _consume_node(
    raw: bytes,
    granularity: int,
    lat_offset: int,
    lon_offset: int,
    accept: Callable[[int, float, float], None],
) -> None:
    node_id = None
    lat = lon = None
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 0:
            node_id = _zigzag(value)
        elif field_no == 8 and wire == 0:
            lat = _zigzag(value)
        elif field_no == 9 and wire == 0:
            lon = _zigzag(value)
    if node_id is None or lat is None or lon is None:
        return
    accept(
        node_id,
        (lon_offset + granularity * lon) * 1e-9,
        (lat_offset + granularity * lat) * 1e-9,
    )


def _delta_sint_refs(raw: bytes) -> List[int]:
    refs: List[int] = []
    acc = 0
    i = 0
    n = len(raw)
    while i < n:
        delta, i = _varint(raw, i)
        acc += _zigzag(delta)
        refs.append(acc)
    return refs


def _packed_varints(raw: bytes) -> List[int]:
    values: List[int] = []
    i = 0
    n = len(raw)
    while i < n:
        value, i = _varint(raw, i)
        values.append(value)
    return values


def _parse_way(raw: bytes, strings: Sequence[str]) -> Optional[WayRecord]:
    way_id = None
    keys: List[int] = []
    vals: List[int] = []
    refs: List[int] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 0:
            way_id = _signed64(value)
        elif field_no == 2 and wire == 2:
            keys = _packed_varints(value)
        elif field_no == 3 and wire == 2:
            vals = _packed_varints(value)
        elif field_no == 8 and wire == 2:
            refs = _delta_sint_refs(value)
    if way_id is None or len(refs) < 2 or len(keys) != len(vals):
        return None
    tags: Dict[str, str] = {}
    n_strings = len(strings)
    for key_id, val_id in zip(keys, vals):
        if 0 <= key_id < n_strings and 0 <= val_id < n_strings:
            tags[strings[key_id]] = strings[val_id]
    return way_id, tags, refs


def _scan_block_ways(
    raw: bytes,
    nodes: NodeTable,
    highway_types: set,
    out: List[WayRecord],
) -> None:
    strings = [""]
    groups: List[bytes] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 2:
            strings = _string_table(value)
        elif field_no == 2 and wire == 2:
            groups.append(value)
    node_ids = nodes
    for group in groups:
        for field_no, wire, value in iter_fields(group):
            if field_no != 3 or wire != 2:
                continue
            parsed = _parse_way(value, strings)
            if parsed is None:
                continue
            way_id, tags, refs = parsed
            highway = tags.get("highway", "")
            if highway not in highway_types:
                continue
            if any(ref in node_ids for ref in refs):
                out.append((way_id, tags, refs))


def read_pbf_header(path: str) -> dict:
    for blob_type, raw in iter_file_blobs(path):
        if blob_type == "OSMHeader":
            return parse_header_block(raw)
        break
    raise ValueError(f"OSM PBF has no header block: {path}")


def collect_highway_ways(
    path: str,
    lonlat_window: Sequence[float],
    highway_types: set,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[dict, NodeTable, List[WayRecord]]:
    """Return ``(header, nodes, ways)`` for highways touching ``lonlat_window``.

    ``lonlat_window`` is ``(west, south, east, north)`` in degrees. Nodes
    outside that window are discarded, so a way is kept only when at least
    one of its nodes was stored. Callers should pad the window.
    """
    west, south, east, north = [float(v) for v in lonlat_window]
    if west >= east or south >= north:
        raise ValueError(f"invalid lon/lat window: {lonlat_window}")

    header: dict = {}
    nodes: NodeTable = {}

    def accept(node_id: int, lon: float, lat: float) -> None:
        if west <= lon <= east and south <= lat <= north:
            nodes[node_id] = (round(lon, 7), round(lat, 7))

    blobs = 0
    for blob_type, raw in iter_file_blobs(path):
        blobs += 1
        if blob_type == "OSMHeader":
            header = parse_header_block(raw)
        elif blob_type == "OSMData":
            _scan_block_nodes(raw, accept)
        if progress and blobs % 25 == 0:
            progress(f"PBF node pass: {blobs} blobs, nodes in window={len(nodes)}")
    if progress:
        progress(f"PBF node pass done: {blobs} blobs, nodes in window={len(nodes)}")

    ways: List[WayRecord] = []
    blobs = 0
    for blob_type, raw in iter_file_blobs(path):
        blobs += 1
        if blob_type == "OSMData":
            _scan_block_ways(raw, nodes, highway_types, ways)
        if progress and blobs % 25 == 0:
            progress(f"PBF way pass: {blobs} blobs, ways={len(ways)}")
    if progress:
        progress(f"PBF way pass done: ways={len(ways)}")
    if not header:
        raise ValueError(f"OSM PBF has no header block: {path}")
    return header, nodes, ways


def _parse_relation(raw: bytes, strings: Sequence[str]) -> Optional[BoundaryRelation]:
    rel_id = None
    keys: List[int] = []
    vals: List[int] = []
    roles: List[int] = []
    memids: List[int] = []
    types: List[int] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 0:
            rel_id = _signed64(value)
        elif field_no == 2 and wire == 2:
            keys = _packed_varints(value)
        elif field_no == 3 and wire == 2:
            vals = _packed_varints(value)
        elif field_no == 8 and wire == 2:
            roles = _packed_varints(value)
        elif field_no == 9 and wire == 2:
            memids = _delta_sint_refs(value)
        elif field_no == 10 and wire == 2:
            types = _packed_varints(value)
    if rel_id is None or len(keys) != len(vals):
        return None
    tags: Dict[str, str] = {}
    n_strings = len(strings)
    for key_id, val_id in zip(keys, vals):
        if 0 <= key_id < n_strings and 0 <= val_id < n_strings:
            tags[strings[key_id]] = strings[val_id]
    if tags.get("boundary") != "administrative":
        return None
    outer: List[int] = []
    inner: List[int] = []
    if len(roles) == len(memids) == len(types):
        for role_id, ref, mtype in zip(roles, memids, types):
            if mtype != 1 or not (0 <= role_id < n_strings):
                continue
            role = strings[role_id]
            if role == "outer":
                outer.append(ref)
            elif role == "inner":
                inner.append(ref)
    return rel_id, tags, outer, inner


def _scan_block_relations(
    raw: bytes,
    admin_levels: set,
    out: List[BoundaryRelation],
) -> None:
    strings = [""]
    groups: List[bytes] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 1 and wire == 2:
            strings = _string_table(value)
        elif field_no == 2 and wire == 2:
            groups.append(value)
    for group in groups:
        for field_no, wire, value in iter_fields(group):
            if field_no != 4 or wire != 2:
                continue
            parsed = _parse_relation(value, strings)
            if parsed is None:
                continue
            if parsed[1].get("admin_level") in admin_levels:
                out.append(parsed)


def _scan_block_way_refs(
    raw: bytes,
    wanted: set,
    out: Dict[int, List[int]],
) -> None:
    groups: List[bytes] = []
    for field_no, wire, value in iter_fields(raw):
        if field_no == 2 and wire == 2:
            groups.append(value)
    for group in groups:
        for field_no, wire, value in iter_fields(group):
            if field_no != 3 or wire != 2:
                continue
            way_id = None
            refs: List[int] = []
            for fno, fwire, fvalue in iter_fields(value):
                if fno == 1 and fwire == 0:
                    way_id = _signed64(fvalue)
                elif fno == 8 and fwire == 2:
                    refs = _delta_sint_refs(fvalue)
            if way_id in wanted and len(refs) >= 2:
                out[way_id] = refs


def collect_boundary_relations(
    path: str,
    admin_levels: set,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[dict, List[BoundaryRelation]]:
    """Return ``(header, relations)`` for ``boundary=administrative`` at ``admin_levels``.

    Only way members with role ``outer``/``inner`` are kept; node members and
    subareas are ignored. Ring assembly is the caller's job.
    """
    header: dict = {}
    relations: List[BoundaryRelation] = []
    blobs = 0
    for blob_type, raw in iter_file_blobs(path):
        blobs += 1
        if blob_type == "OSMHeader":
            header = parse_header_block(raw)
        elif blob_type == "OSMData":
            _scan_block_relations(raw, admin_levels, relations)
        if progress and blobs % 200 == 0:
            progress(f"PBF relation pass: {blobs} blobs, relations={len(relations)}")
    if not header:
        raise ValueError(f"OSM PBF has no header block: {path}")
    return header, relations


def collect_way_refs(
    path: str,
    way_ids: set,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[int, List[int]]:
    """Return node ref lists for the requested way ids (missing ways are absent)."""
    way_refs: Dict[int, List[int]] = {}
    blobs = 0
    for blob_type, raw in iter_file_blobs(path):
        blobs += 1
        if blob_type == "OSMData":
            _scan_block_way_refs(raw, way_ids, way_refs)
        if progress and blobs % 200 == 0:
            progress(f"PBF way-ref pass: {blobs} blobs, ways={len(way_refs)}")
    return way_refs


def collect_nodes(
    path: str,
    node_ids: set,
    progress: Optional[Callable[[str], None]] = None,
) -> NodeTable:
    """Return ``(lon, lat)`` for the requested node ids (missing nodes are absent)."""
    nodes: NodeTable = {}

    def accept(node_id: int, lon: float, lat: float) -> None:
        if node_id in node_ids:
            nodes[node_id] = (round(lon, 7), round(lat, 7))

    blobs = 0
    for blob_type, raw in iter_file_blobs(path):
        blobs += 1
        if blob_type == "OSMData":
            _scan_block_nodes(raw, accept)
        if progress and blobs % 200 == 0:
            progress(f"PBF node pass: {blobs} blobs, nodes={len(nodes)}")
    return nodes
