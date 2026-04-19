#!/usr/bin/env python3
"""Search contour fragments in font B from font A single-stroke contour prior.

Key idea: transfer *correspondence prior* (shape + relative position), not raw point IDs.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

try:
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont
except Exception:  # pragma: no cover
    TTFont = None
    RecordingPen = None

try:
    from svgpathtools import parse_path
except Exception:  # pragma: no cover
    parse_path = None

Point = Tuple[float, float]
BBox = Tuple[float, float, float, float]


@dataclass
class Prior:
    points: List[Point]
    rel_center: Point
    rel_size: Point


@dataclass
class Match:
    character: str
    contour_index: int
    start_index: int
    score: float
    shape_score: float
    position_score: float
    curvature_score: float
    glyph_kind: str


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bbox(points: Sequence[Point]) -> BBox:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_center_size(box: BBox) -> Tuple[Point, Point]:
    x0, y0, x1, y1 = box
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0), (max(1e-8, x1 - x0), max(1e-8, y1 - y0))


def normalize_to_bbox(points: Sequence[Point], box: BBox) -> List[Point]:
    x0, y0, x1, y1 = box
    w = max(1e-8, x1 - x0)
    h = max(1e-8, y1 - y0)
    return [((x - x0) / w, (y - y0) / h) for x, y in points]


def resample_polyline(points: Sequence[Point], n: int) -> List[Point]:
    if len(points) < 2:
        return list(points)

    segments = [_dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(segments)
    if total == 0:
        return [points[0]] * n

    targets = [i * total / (n - 1) for i in range(n)]
    out: List[Point] = []
    seg_i = 0
    walked = 0.0

    for t in targets:
        while seg_i < len(segments) - 1 and walked + segments[seg_i] < t:
            walked += segments[seg_i]
            seg_i += 1
        seg_len = segments[seg_i]
        if seg_len == 0:
            out.append(points[seg_i])
            continue
        alpha = (t - walked) / seg_len
        x0, y0 = points[seg_i]
        x1, y1 = points[seg_i + 1]
        out.append((x0 + alpha * (x1 - x0), y0 + alpha * (y1 - y0)))
    return out


def normalize_points(points: Sequence[Point]) -> List[Point]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = statistics.fmean(xs)
    cy = statistics.fmean(ys)
    centered = [(x - cx, y - cy) for x, y in points]
    scale = math.sqrt(sum(x * x + y * y for x, y in centered) / max(1, len(centered)))
    if scale == 0:
        return centered
    return [(x / scale, y / scale) for x, y in centered]


def symmetric_chamfer(a: Sequence[Point], b: Sequence[Point]) -> float:
    def directed(p: Sequence[Point], q: Sequence[Point]) -> float:
        return sum(min(_dist(x, y) for y in q) for x in p) / max(1, len(p))

    return 0.5 * (directed(a, b) + directed(b, a))


def turning_angles(points: Sequence[Point]) -> List[float]:
    angles: List[float] = []
    for i in range(1, len(points) - 1):
        p0, p1, p2 = points[i - 1], points[i], points[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        n1 = math.hypot(v1[0], v1[1])
        n2 = math.hypot(v2[0], v2[1])
        if n1 < 1e-8 or n2 < 1e-8:
            angles.append(0.0)
            continue
        dot = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        angles.append(math.acos(dot) / math.pi)
    return angles


def l2(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)) / n)


def read_stroke_path(graphics_path: pathlib.Path, char: str, stroke_idx: int) -> str:
    with graphics_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("character") != char:
                continue
            strokes = row.get("strokes", [])
            if stroke_idx < 0 or stroke_idx >= len(strokes):
                raise IndexError(f"Stroke index out of range: {stroke_idx} (total {len(strokes)})")
            return strokes[stroke_idx]
    raise ValueError(f"Character not found in graphics.txt: {char}")


def sample_svg_path(path_d: str, n: int) -> List[Point]:
    if parse_path is None:
        raise RuntimeError("svgpathtools is required. Please `pip install -r contour_search/requirements.txt`.")
    path = parse_path(path_d)
    total = path.length(error=1e-3)
    if total == 0:
        return [(0.0, 0.0)] * n
    pts = [path.point(path.ilength(i * total / (n - 1), error=1e-3)) for i in range(n)]
    return [(float(p.real), float(p.imag)) for p in pts]


def quad(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    u = 1 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def glyph_kind(font: TTFont, ch: str) -> str:
    if "glyf" not in font:
        return "unknown"
    cmap = font.getBestCmap()
    gn = cmap.get(ord(ch))
    if not gn:
        return "missing"
    g = font["glyf"][gn]
    return "composite" if g.isComposite() else "simple"


def glyph_contours(font: TTFont, ch: str, curve_steps: int = 12) -> List[List[Point]]:
    cmap = font.getBestCmap()
    cp = ord(ch)
    if cp not in cmap:
        return []
    glyph_name = cmap[cp]
    glyph_set = font.getGlyphSet()
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)

    contours: List[List[Point]] = []
    current: List[Point] = []
    cursor: Point | None = None
    start_point: Point | None = None

    for cmd, args in pen.value:
        if cmd == "moveTo":
            if current:
                contours.append(current)
            p = tuple(map(float, args[0]))
            current = [p]
            cursor = p
            start_point = p
        elif cmd == "lineTo":
            p = tuple(map(float, args[0]))
            current.append(p)
            cursor = p
        elif cmd == "qCurveTo":
            if cursor is None:
                continue
            controls = [tuple(map(float, a)) for a in args]
            end = controls[-1]
            for c in controls[:-1]:
                for i in range(1, curve_steps + 1):
                    current.append(quad(cursor, c, end, i / curve_steps))
                cursor = end
        elif cmd == "curveTo":
            if cursor is None:
                continue
            c1, c2, end = [tuple(map(float, a)) for a in args]
            for i in range(1, curve_steps + 1):
                current.append(cubic(cursor, c1, c2, end, i / curve_steps))
            cursor = end
        elif cmd == "closePath":
            if current and start_point and current[-1] != start_point:
                current.append(start_point)
            if current:
                contours.append(current)
            current = []
            cursor = None
            start_point = None

    if current:
        contours.append(current)
    return [c for c in contours if len(c) >= 2]


def iter_windows(contour: Sequence[Point], window_points: int, stride: int) -> Iterable[Tuple[int, List[Point]]]:
    if len(contour) < window_points:
        return
    for start in range(0, len(contour) - window_points + 1, stride):
        yield start, list(contour[start : start + window_points])


def build_prior(graphics_path: pathlib.Path, char: str, stroke_idx: int, sample_points: int) -> Prior:
    prior_path = read_stroke_path(graphics_path, char, stroke_idx)
    raw = sample_svg_path(prior_path, sample_points)

    # MakeMeAHanzi canonical coordinate system is known.
    char_box = (0.0, -124.0, 1024.0, 900.0)
    raw_in_char = normalize_to_bbox(raw, char_box)

    pbox = bbox(raw_in_char)
    center, size = bbox_center_size(pbox)
    return Prior(points=normalize_points(raw_in_char), rel_center=center, rel_size=size)


def glyph_level_normalize(contours: Sequence[Sequence[Point]]) -> List[List[Point]]:
    all_pts = [p for c in contours for p in c]
    if not all_pts:
        return []
    gbox = bbox(all_pts)
    return [normalize_to_bbox(c, gbox) for c in contours]


def search(
    graphics_path: pathlib.Path,
    char_a: str,
    stroke_idx: int,
    font_b_path: pathlib.Path,
    candidate_chars: Sequence[str],
    sample_points: int,
    window_points: int,
    stride: int,
    topk: int,
    w_shape: float,
    w_pos: float,
    w_curv: float,
) -> List[Match]:
    if TTFont is None:
        raise RuntimeError("fonttools is required. Please `pip install -r contour_search/requirements.txt`.")

    prior = build_prior(graphics_path, char_a, stroke_idx, sample_points)
    prior_angles = turning_angles(prior.points)

    font_b = TTFont(str(font_b_path))
    matches: List[Match] = []

    for ch in candidate_chars:
        raw_contours = glyph_contours(font_b, ch)
        contours = glyph_level_normalize(raw_contours)
        g_kind = glyph_kind(font_b, ch)

        for ci, contour in enumerate(contours):
            for start, window in iter_windows(contour, window_points, stride):
                sampled = resample_polyline(window, sample_points)
                sampled_norm = normalize_points(sampled)
                shape_score = symmetric_chamfer(prior.points, sampled_norm)

                wbox = bbox(sampled)
                w_center, w_size = bbox_center_size(wbox)
                position_score = _dist(w_center, prior.rel_center) + 0.5 * _dist(w_size, prior.rel_size)

                curv_score = l2(prior_angles, turning_angles(sampled_norm))
                score = w_shape * shape_score + w_pos * position_score + w_curv * curv_score

                matches.append(
                    Match(
                        character=ch,
                        contour_index=ci,
                        start_index=start,
                        score=score,
                        shape_score=shape_score,
                        position_score=position_score,
                        curvature_score=curv_score,
                        glyph_kind=g_kind,
                    )
                )

    matches.sort(key=lambda m: m.score)
    return matches[:topk]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graphics", type=pathlib.Path, default=pathlib.Path("graphics.txt"))
    parser.add_argument("--char-a", required=True, help="Font A prior character, e.g. 永")
    parser.add_argument("--stroke-index", type=int, required=True, help="Stroke index in graphics.txt")
    parser.add_argument("--font-b", type=pathlib.Path, required=True, help="Path to font B (.otf/.ttf)")
    parser.add_argument("--candidate-chars", default="", help="Characters to search in font B. Default: --char-a.")
    parser.add_argument("--sample-points", type=int, default=64)
    parser.add_argument("--window-points", type=int, default=64)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--w-shape", type=float, default=1.0, help="Weight for shape similarity term.")
    parser.add_argument("--w-pos", type=float, default=0.7, help="Weight for relative-position prior term.")
    parser.add_argument("--w-curv", type=float, default=0.4, help="Weight for local-curvature term.")
    args = parser.parse_args()

    candidates = list(args.candidate_chars) if args.candidate_chars else [args.char_a]

    try:
        results = search(
            graphics_path=args.graphics,
            char_a=args.char_a,
            stroke_idx=args.stroke_index,
            font_b_path=args.font_b,
            candidate_chars=candidates,
            sample_points=args.sample_points,
            window_points=args.window_points,
            stride=args.stride,
            topk=args.topk,
            w_shape=args.w_shape,
            w_pos=args.w_pos,
            w_curv=args.w_curv,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("rank\tchar\tglyph_kind\tcontour\tstart\tscore\tshape\tpos\tcurv")
    for i, m in enumerate(results, 1):
        print(
            f"{i}\t{m.character}\t{m.glyph_kind}\t{m.contour_index}\t{m.start_index}"
            f"\t{m.score:.6f}\t{m.shape_score:.6f}\t{m.position_score:.6f}\t{m.curvature_score:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
