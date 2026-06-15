#!/usr/bin/env python3
"""Apply visual degradation to image folders or extracted rosbag frames.

Examples:
  python degrade_dataset.py --input frames/ --output degraded/blur5 --type gaussian --level 5
  python degrade_dataset.py --input frames/ --output degraded/occl25 --type occlusion --level 25
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np


def gaussian_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return img.copy()
    k = int(2 * round(sigma) + 1)
    k = max(k, 3) | 1
    return cv2.GaussianBlur(img, (k, k), sigmaX=sigma)


def motion_blur(img: np.ndarray, length_px: int) -> np.ndarray:
    if length_px <= 0:
        return img.copy()
    kernel = np.zeros((length_px, length_px), dtype=np.float32)
    kernel[length_px // 2, :] = 1.0
    kernel /= kernel.sum()
    return cv2.filter2D(img, -1, kernel)


def brightness(img: np.ndarray, percent: float) -> np.ndarray:
    scale = 1.0 + percent / 100.0
    out = np.clip(img.astype(np.float32) * scale, 0, 255)
    return out.astype(np.uint8)


def texture_loss(img: np.ndarray, sigma: float, contrast: float) -> np.ndarray:
    blurred = gaussian_blur(img, sigma)
    mean = blurred.mean(axis=(0, 1), keepdims=True)
    out = mean + contrast * (blurred.astype(np.float32) - mean)
    return np.clip(out, 0, 255).astype(np.uint8)


def occlusion(img: np.ndarray, percent: float) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    occ_h = int(h * percent / 100.0)
    out[:occ_h, :, :] = 0
    return out


DEGRADERS = {
    "gaussian": lambda img, level: gaussian_blur(img, float(level)),
    "motion": lambda img, level: motion_blur(img, int(level)),
    "brightness": lambda img, level: brightness(img, float(level)),
    "texture": lambda img, level: texture_loss(img, sigma=5.0, contrast=0.5),
    "occlusion": lambda img, level: occlusion(img, float(level)),
}


def iter_images(input_dir: Path):
    exts = {".png", ".jpg", ".jpeg", ".bmp"}
    for path in sorted(input_dir.rglob("*")):
        if path.suffix.lower() in exts:
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="Degrade visual data for VIO experiments")
    parser.add_argument("--input", type=Path, required=True, help="Folder with source images")
    parser.add_argument("--output", type=Path, required=True, help="Output folder")
    parser.add_argument(
        "--type",
        choices=sorted(DEGRADERS),
        required=True,
        help="Degradation type",
    )
    parser.add_argument("--level", type=float, required=True, help="Degradation strength")
    parser.add_argument("--copy-non-images", action="store_true", help="Copy other files as-is")
    args = parser.parse_args()

    if not args.input.is_dir():
        raise SystemExit(f"Input directory not found: {args.input}")

    degrade = DEGRADERS[args.type]
    image_paths = list(iter_images(args.input))
    if not image_paths:
        raise SystemExit(f"No images found under {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)

    for src in image_paths:
        rel = src.relative_to(args.input)
        dst = args.output / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Failed to read image: {src}")
        cv2.imwrite(str(dst), degrade(img, args.level))

    if args.copy_non_images:
        image_set = {p.resolve() for p in image_paths}
        for path in args.input.rglob("*"):
            if path.is_file() and path.resolve() not in image_set:
                rel = path.relative_to(args.input)
                dst = args.output / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst)

    print(f"Processed {len(image_paths)} images -> {args.output}")


if __name__ == "__main__":
    main()
