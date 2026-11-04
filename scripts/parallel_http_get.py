#!/usr/bin/env python3
"""Resume-capable parallel HTTP Range downloader.

Writes verified chunk files under <dest>.parts/, then concatenates.
Does not sparse-truncate the destination (that previously looked 'complete').
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen


def _read_exact(url: str, start: int, length: int, timeout: int = 60) -> bytes:
    end = start + length - 1
    req = Request(
        url,
        headers={
            "Range": f"bytes={start}-{end}",
            "User-Agent": "aspiranture-parallel-get/2",
        },
    )
    buf = bytearray()
    with urlopen(req, timeout=timeout) as resp:
        while len(buf) < length:
            chunk = resp.read(min(256 * 1024, length - len(buf)))
            if not chunk:
                break
            buf.extend(chunk)
    if len(buf) != length:
        raise IOError(f"short read {start}-{end}: got {len(buf)} want {length}")
    return bytes(buf)


def download(url: str, dest: str, total: int, workers: int = 8, chunk: int = 4 * 1024 * 1024) -> int:
    dest_p = Path(dest).resolve()
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = dest_p.parent / (dest_p.name + ".parts")
    parts_dir.mkdir(exist_ok=True)

    prefix = 0
    if dest_p.is_file():
        # Keep only a contiguous prefix: stop at first unallocated hole via SEEK_DATA/HOLE.
        with dest_p.open("rb") as fh:
            try:
                hole = os.lseek(fh.fileno(), 0, os.SEEK_HOLE)
            except OSError:
                hole = dest_p.stat().st_size
            prefix = min(hole, total)
        if prefix >= total:
            print(f"Already complete: {dest_p}")
            return 0
        if prefix > 0:
            pref_path = parts_dir / f"{0:016d}_{prefix:016d}"
            if not pref_path.is_file() or pref_path.stat().st_size != prefix:
                print(f"Saving contiguous prefix {prefix} bytes", flush=True)
                with dest_p.open("rb") as src, pref_path.open("wb") as out:
                    remaining = prefix
                    while remaining:
                        block = src.read(min(8 * 1024 * 1024, remaining))
                        if not block:
                            break
                        out.write(block)
                        remaining -= len(block)
                if pref_path.stat().st_size != prefix:
                    print("ERROR: failed to extract prefix", file=sys.stderr)
                    return 1

    # Drop sparse/corrupt destination; we rebuild from parts.
    if dest_p.exists():
        dest_p.unlink()

    jobs: list[tuple[int, int]] = []
    if prefix > 0:
        jobs.append((0, prefix))
    pos = prefix
    while pos < total:
        n = min(chunk, total - pos)
        jobs.append((pos, n))
        pos += n

    todo: list[tuple[int, int]] = []
    have = 0
    for start, length in jobs:
        part = parts_dir / f"{start:016d}_{start + length:016d}"
        if part.is_file() and part.stat().st_size == length:
            have += length
        else:
            todo.append((start, length))

    print(
        f"{url}\n  -> {dest_p}\n  have={have}/{total} remaining_chunks={len(todo)} "
        f"workers={workers} chunk={chunk}",
        flush=True,
    )
    t0 = time.time()
    done = have
    done_lock = threading.Lock()

    def job(start: int, length: int) -> None:
        nonlocal done
        part = parts_dir / f"{start:016d}_{start + length:016d}"
        tmp = part.with_suffix(".tmp")
        attempts = 0
        while True:
            attempts += 1
            try:
                data = _read_exact(url, start, length)
                tmp.write_bytes(data)
                tmp.replace(part)
                with done_lock:
                    done += length
                    cur = done
                elapsed = max(time.time() - t0, 1e-6)
                speed = (cur - have) / elapsed
                print(
                    f"  {100 * cur / total:5.1f}% +{start} ({length} B) "
                    f"{speed / 1024:.1f} KiB/s",
                    flush=True,
                )
                return
            except Exception as exc:
                if attempts >= 12:
                    raise
                wait = min(40, 2 * attempts)
                print(f"  retry {attempts} @{start}: {exc} (sleep {wait}s)", flush=True)
                time.sleep(wait)

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(job, s, n) for s, n in todo]
            for fut in as_completed(futs):
                fut.result()

    with dest_p.open("wb") as out:
        for start, length in jobs:
            part = parts_dir / f"{start:016d}_{start + length:016d}"
            if not part.is_file() or part.stat().st_size != length:
                print(f"ERROR: missing part {part}", file=sys.stderr)
                return 1
            with part.open("rb") as src:
                while True:
                    buf = src.read(8 * 1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    if dest_p.stat().st_size != total:
        print(f"ERROR: assembled size {dest_p.stat().st_size} != {total}", file=sys.stderr)
        return 1

    # Cleanup parts to free disk.
    for p in parts_dir.iterdir():
        p.unlink()
    parts_dir.rmdir()
    print(f"DONE {dest_p} ({total} bytes)", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--total", type=int, required=True)
    p.add_argument("-x", "--workers", type=int, default=8)
    p.add_argument("--chunk", type=int, default=4 * 1024 * 1024)
    args = p.parse_args()
    return download(args.url, args.output, args.total, args.workers, args.chunk)


if __name__ == "__main__":
    raise SystemExit(main())
