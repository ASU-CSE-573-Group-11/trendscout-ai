from __future__ import annotations

import argparse
from pathlib import Path

from collectors.pipeline import run_sueda_collection, write_collection_bundle
from retrieval.bm25 import BM25Index


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Sueda's news, voice, company, and YC identity records."
    )
    parser.add_argument("--live", action="store_true", help="Fetch permitted public RSS feeds.")
    parser.add_argument("--youtube", action="store_true", help="Collect YouTube public metadata if an API key is set.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/sueda"),
        help="Local output directory. Raw and processed data stay uncommitted.",
    )
    parser.add_argument("--query", default="", help="Optional BM25 query to print after collection.")
    args = parser.parse_args()

    result = run_sueda_collection(live=args.live, include_youtube=args.youtube)
    write_collection_bundle(result, args.out)
    print(json_stats(result))
    if args.query:
        index = BM25Index.from_records(result["accepted"])
        hits = index.search(args.query, k=5)
        for hit in hits:
            print(f"{hit['score']:.3f}\t{hit['record']['title']}\t{hit['record']['source_url']}")


def json_stats(result: dict) -> str:
    import json

    return json.dumps(result["stats"], indent=2)


if __name__ == "__main__":
    main()
