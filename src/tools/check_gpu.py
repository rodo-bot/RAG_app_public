"""Verify that the optional indexing runtime really uses CUDA."""

from pathlib import Path
import onnxruntime as ort
from fastembed import TextEmbedding


def main() -> int:
    if "CUDAExecutionProvider" not in ort.get_available_providers():
        print("CUDAExecutionProvider is unavailable")
        return 1
    ort.preload_dlls(directory="")
    root = Path(__file__).resolve().parent.parent
    model = TextEmbedding(
        model_name="BAAI/bge-small-en-v1.5",
        cache_dir=root / "models",
        providers=["CUDAExecutionProvider"],
    )
    providers = model.model.model.get_providers()
    if "CUDAExecutionProvider" not in providers:
        print(f"Model fell back to {providers}")
        return 1
    vector = next(model.embed(["GPU embedding ready"]))
    if len(vector) != 384:
        print("Unexpected embedding dimensions")
        return 1
    print("CUDA embedding verified with a 384-dimensional vector")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
