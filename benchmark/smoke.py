"""在明确标记的合成语料上验证评测链路，不代表科研论文集效果。"""

import json
from dataclasses import asdict, replace

from papermind.config import Settings
from papermind.evaluation.benchmark import RetrievalExample, run_benchmark
from papermind.service import PaperMindService

DOCUMENTS = {
    "synthetic_mamba.txt": "# Method\n\nModel-A uses Mamba state space blocks for image restoration.\n\n"
    "# Experiments\n\nModel-A has 4M parameters. Urban100 x4 PSNR is 27.38 dB.",
    "synthetic_cnn.txt": "# Method\n\nModel-B uses convolutional CNN residual blocks.\n\n"
    "# Experiments\n\nModel-B has 8M parameters. Set14 x2 PSNR is 33.20 dB.",
    "synthetic_transformer.txt": "# Method\n\nModel-C uses window attention Transformer blocks.\n\n"
    "# Experiments\n\nModel-C has 12M parameters. Urban100 x4 PSNR is 27.45 dB.",
}


def main():
    settings = Settings.from_env()
    service = PaperMindService(replace(settings, data_dir=settings.data_dir / "smoke"))
    ids = {}
    for name, text in DOCUMENTS.items():
        uploaded = service.upload(name, text.encode(), "synthetic")
        service.index(uploaded["document_id"], "synthetic")
        ids[name] = uploaded["document_id"]
    a, b, c = [ids[name] for name in DOCUMENTS]
    examples = [
        RetrievalExample(
            "mamba",
            "Which model uses Mamba state space blocks?",
            [f"{a}:0"],
            "synthetic",
        ),
        RetrievalExample(
            "cnn",
            "Which model uses convolutional CNN residual blocks?",
            [f"{b}:0"],
            "synthetic",
        ),
        RetrievalExample(
            "attention", "Which model uses window attention?", [f"{c}:0"], "synthetic"
        ),
        RetrievalExample(
            "urban100",
            "Urban100 x4 PSNR",
            [f"{a}:1", f"{c}:1"],
            "synthetic",
            "comparison",
        ),
        RetrievalExample(
            "missing", "quasar spectroscopy", [], "synthetic", "unanswerable"
        ),
    ]
    result = run_benchmark(service, examples)
    dataset = settings.data_dir / "smoke-questions.jsonl"
    dataset.write_text(
        "\n".join(
            json.dumps(asdict(example), ensure_ascii=False) for example in examples
        )
        + "\n",
        encoding="utf-8",
    )
    result["dataset_kind"] = "synthetic-smoke-only; not a research-quality benchmark"
    output = settings.data_dir / "smoke-results.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "runs": {
                    mode: {
                        key: value for key, value in run.items() if key != "examples"
                    }
                    for mode, run in result["runs"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
