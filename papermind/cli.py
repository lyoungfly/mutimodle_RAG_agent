import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

from papermind.config import Settings
from papermind.service import PaperMindService


def main():
    parser = argparse.ArgumentParser(
        prog="papermind", description="PaperMind 科研文档检索"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest", help="上传并索引 PDF/TXT/MD/CSV/PNG/JPEG/WebP"
    )
    ingest.add_argument("files", nargs="+", type=Path)
    ingest.add_argument("--collection", default="default")
    for command in ("search", "chat"):
        query = commands.add_parser(command)
        query.add_argument("question")
        query.add_argument("--collection", default="default")
        query.add_argument(
            "--mode",
            default="auto",
            choices=[
                "auto",
                "bm25",
                "dense",
                "hybrid",
                "hybrid_rerank",
                "image",
                "multimodal",
                "multimodal_rerank",
            ],
        )
        query.add_argument("-k", type=int, default=5)
    benchmark = commands.add_parser("evaluate", help="运行 JSONL 数据集的检索消融评测")
    benchmark.add_argument("dataset", type=Path)
    benchmark.add_argument(
        "--output", type=Path, default=Path("data/retrieval-results.json")
    )
    serve = commands.add_parser("serve", help="启动本地 API 和演示页面")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "papermind.api.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
        )
        return
    service = PaperMindService(Settings.from_env())
    try:
        if args.command == "ingest":
            result = []
            for path in args.files:
                with path.open("rb") as file:
                    content = file.read(service.settings.max_upload_bytes + 1)
                uploaded = service.upload(path.name, content, args.collection)
                result.append(service.index(uploaded["document_id"], args.collection))
        elif args.command == "search":
            result = [
                asdict(hit)
                for hit in service.search(
                    args.question, args.collection, args.k, mode=args.mode
                )
            ]
        elif args.command == "chat":
            result = service.chat(
                args.question, args.collection, args.k, mode=args.mode
            )
        else:
            from papermind.evaluation.benchmark import evaluate_file

            result = evaluate_file(service, args.dataset, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        parser.exit(1, f"PaperMind: {exc}\n")


if __name__ == "__main__":
    main()
