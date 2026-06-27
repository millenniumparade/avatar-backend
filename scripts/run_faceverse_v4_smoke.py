from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.algorithms.faceverse_v4_adapter import FaceVerseV4Runner, validate_faceverse_v4_assets


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one FaceVerse_v4 image smoke test.")
    parser.add_argument("--image", default="FaceVerse_v4/example/input/test.jpg")
    parser.add_argument("--root", default="FaceVerse_v4")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--allow-cpu-fallback", action="store_true")
    parser.add_argument("--skip-vertices", action="store_true")
    args = parser.parse_args()

    validate_faceverse_v4_assets(args.root)
    runner = FaceVerseV4Runner(
        args.root,
        device_name=args.device,
        allow_cpu_fallback=args.allow_cpu_fallback,
    )
    result = runner.run_image(args.image, compute_vertices=not args.skip_vertices)
    result["model_load_seconds"] = runner.load_seconds
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
