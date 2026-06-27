from __future__ import annotations

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="Check PyTorch CUDA visibility.")
    parser.add_argument("--require-cuda", action="store_true")
    args = parser.parse_args()

    import torch

    cuda_available = torch.cuda.is_available()
    result = {
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "cuda_available": cuda_available,
        "device_count": torch.cuda.device_count() if cuda_available else 0,
        "devices": [],
    }

    if cuda_available:
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            result["devices"].append(
                {
                    "index": index,
                    "name": props.name,
                    "total_memory_mb": round(props.total_memory / 1024 / 1024, 2),
                    "major": props.major,
                    "minor": props.minor,
                }
            )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.require_cuda and not cuda_available:
        raise SystemExit("CUDA is required but torch.cuda.is_available() is false.")


if __name__ == "__main__":
    main()
