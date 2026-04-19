#!/usr/bin/env python3
"""Download Source Han Serif (思源宋体) font file for contour search experiments."""

from __future__ import annotations

import argparse
import pathlib
import sys
import urllib.request

DEFAULT_URL = (
    "https://github.com/adobe-fonts/source-han-serif/raw/release/"
    "OTF/SimplifiedChinese/SourceHanSerifSC-Regular.otf"
)


def download(url: str, output: pathlib.Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        data = response.read()
    output.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Source Han Serif font URL (default: SC Regular from adobe-fonts/source-han-serif).",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("fonts/SourceHanSerifSC-Regular.otf"),
        help="Where to save the downloaded .otf file.",
    )
    args = parser.parse_args()

    try:
        download(args.url, args.output)
    except Exception as exc:  # pragma: no cover
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Downloaded to {args.output} ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
