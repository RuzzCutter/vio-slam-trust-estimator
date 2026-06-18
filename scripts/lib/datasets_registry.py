#!/usr/bin/env python3
"""Dataset catalog: list, install status, metadata, download helpers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
CATALOG_PATH = CONFIG_DIR / "datasets.yaml"
CUSTOM_PATH = CONFIG_DIR / "datasets_custom.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML required: pip install pyyaml")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def load_catalog() -> dict[str, Any]:
    catalog = _load_yaml(CATALOG_PATH)
    custom = _load_yaml(CUSTOM_PATH)
    seqs = dict(catalog.get("sequences") or {})
    seqs.update(custom.get("sequences") or {})
    catalog["sequences"] = seqs
    return catalog


def data_root() -> Path:
    import os

    return Path(os.environ.get("DATA_ROOT", ROOT / "datasets"))


def ros2_bag_path(seq_id: str, meta: dict[str, Any] | None = None) -> Path:
    meta = meta or get_sequence(seq_id)
    bag = meta.get("bag") or {}
    if bag.get("type") == "local":
        p = Path(bag["path"])
        return p if p.is_absolute() else ROOT / p
    family = meta.get("family", "euroc_mav")
    cat = load_catalog()
    fam = (cat.get("families") or {}).get(family, {})
    bag_dir = fam.get("bag_dir", "euroc")
    return data_root() / bag_dir / f"{seq_id}_ros2"


def is_installed(seq_id: str) -> bool:
    meta = get_sequence(seq_id)
    p = ros2_bag_path(seq_id, meta)
    return p.is_dir() and (p / "metadata.yaml").is_file()


def get_sequence(seq_id: str) -> dict[str, Any]:
    cat = load_catalog()
    seqs = cat.get("sequences") or {}
    if seq_id not in seqs:
        raise KeyError(f"Unknown sequence: {seq_id}")
    meta = dict(seqs[seq_id])
    meta.setdefault("family", "euroc_mav")
    return meta


def list_sequences(*, tier: str | None = None, installed_only: bool = False) -> list[dict[str, Any]]:
    cat = load_catalog()
    out: list[dict[str, Any]] = []
    for seq_id, meta in sorted((cat.get("sequences") or {}).items()):
        if tier and meta.get("tier") != tier:
            continue
        inst = is_installed(seq_id)
        if installed_only and not inst:
            continue
        out.append(
            {
                "id": seq_id,
                "label": meta.get("label", seq_id),
                "tier": meta.get("tier"),
                "family": meta.get("family", "euroc_mav"),
                "installed": inst,
                "has_gt": gt_path(seq_id) is not None,
                "start_offset": meta.get("start_offset", 0),
                "expected_path_m": meta.get("expected_path_m"),
            }
        )
    return out


def bundle_sequences(bundle: str) -> list[str]:
    cat = load_catalog()
    bundles = cat.get("bundles") or {}
    if bundle not in bundles:
        raise KeyError(f"Unknown bundle: {bundle}")
    return list(bundles[bundle])


def gt_path(seq_id: str) -> Path | None:
    meta = get_sequence(seq_id)
    gt = meta.get("gt_file")
    if not gt:
        return None
    p = Path(gt)
    if p.is_absolute():
        return p if p.is_file() else None
    candidate = ROOT / p
    if candidate.is_file():
        return candidate
    euroc = ROOT / "ws_vins/src/open_vins/ov_data/euroc_mav" / gt
    return euroc if euroc.is_file() else None


def query(seq_id: str, key: str) -> str | None:
    """Single-field lookup for bash scripts (query SEQ KEY)."""
    meta = get_sequence(seq_id)
    if key == "bag_path":
        return str(ros2_bag_path(seq_id, meta))
    if key == "gt_path":
        p = gt_path(seq_id)
        return str(p) if p else None
    if key == "has_gt":
        return "1" if gt_path(seq_id) else "0"
    if key == "expected_path_m":
        v = meta.get("expected_path_m")
        return str(v) if v is not None else None
    if key == "openvins_config":
        fam = (load_catalog().get("families") or {}).get(meta.get("family", "euroc_mav"), {})
        return str(meta.get("openvins_config") or fam.get("openvins_config") or "euroc_mav")
    val = meta.get(key)
    if val is None:
        return None
    return str(val)


def save_custom_sequence(seq_id: str, entry: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML required")
    custom = _load_yaml(CUSTOM_PATH)
    seqs = custom.setdefault("sequences", {})
    seqs[seq_id] = entry
    CUSTOM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CUSTOM_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(custom, f, allow_unicode=True, sort_keys=False)


def download_via_script(seq_ids: list[str], *, source: str = "ethz-rc", ros2: bool = True) -> int:
    script = ROOT / "scripts" / "download_datasets.sh"
    cmd = ["bash", str(script), "--source", source]
    if ros2:
        cmd.append("--ros2")
    for s in seq_ids:
        cmd.extend(["--seq", s])
    import subprocess

    return subprocess.call(cmd)


def cli_list(args: argparse.Namespace) -> int:
    for row in list_sequences(tier=args.tier, installed_only=args.installed):
        mark = "✓" if row["installed"] else "·"
        gt = "GT" if row["has_gt"] else "—"
        print(f"{mark} {row['id']:18} [{gt}] {row['label']}")
    return 0


def cli_meta(args: argparse.Namespace) -> int:
    meta = get_sequence(args.seq)
    meta["installed"] = is_installed(args.seq)
    meta["bag_path"] = str(ros2_bag_path(args.seq, meta))
    if args.key:
        val = meta.get(args.key)
        if val is None:
            return 1
        print(val)
        return 0
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


def cli_query(args: argparse.Namespace) -> int:
    val = query(args.seq, args.key)
    if val is None:
        return 1
    print(val)
    return 0


def cli_download(args: argparse.Namespace) -> int:
    ids = args.seq or bundle_sequences(args.bundle)
    return download_via_script(ids, source=args.source, ros2=not args.ros1_only)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dataset catalog utilities")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="List sequences")
    p_list.add_argument("--tier", choices=["smoke", "benchmark", "optional"])
    p_list.add_argument("--installed", action="store_true")
    p_list.set_defaults(func=cli_list)

    p_meta = sub.add_parser("meta", help="Sequence metadata")
    p_meta.add_argument("seq")
    p_meta.add_argument("key", nargs="?", help="Single field (e.g. start_offset)")
    p_meta.set_defaults(func=cli_meta)

    p_query = sub.add_parser("query", help="Print one metadata field (for bash)")
    p_query.add_argument("seq")
    p_query.add_argument("key")
    p_query.set_defaults(func=cli_query)

    p_dl = sub.add_parser("download", help="Download sequence(s)")
    p_dl.add_argument("--seq", action="append", help="Sequence id (repeatable)")
    p_dl.add_argument("--bundle", choices=["minimal", "full"], default="minimal")
    p_dl.add_argument("--source", default="ethz-rc", choices=["ethz-rc", "gdrive", "ethz-legacy"])
    p_dl.add_argument("--ros1-only", action="store_true")
    p_dl.set_defaults(func=cli_download)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
