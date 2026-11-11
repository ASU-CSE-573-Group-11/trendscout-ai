"""Collect public API records or replay a saved snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from jsonschema import ValidationError

from .api_http import HttpClient
from .common import API_COLLECTOR_VERSION, CollectorError, utc_timestamp
from .sources import COLLECTORS, GitHubCollector, LeverCollector, normalize, snapshot_header


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--source", choices=COLLECTORS)
    selection.add_argument("--replay", type=Path, help="Replay a frozen snapshot without network access")
    parser.add_argument("--target", help="Board slug or GitHub owner/repo")
    parser.add_argument("--company-id", help="Team-agreed canonical company ID")
    parser.add_argument("--company-name")
    parser.add_argument("--origin-cluster-id", help="Override documentary origin; default is canonical URL hash")
    parser.add_argument("--region", choices=["global", "eu"], default="global", help="Lever only")
    parser.add_argument("--window-days", type=int, default=7, help="GitHub only, trailing observation window")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/collectors"))
    args = parser.parse_args(argv)
    if args.source and not all((args.target, args.company_id, args.company_name)):
        parser.error("Live collection requires --target, --company-id, and --company-name")
    if args.replay and any((args.target, args.company_id, args.company_name, args.origin_cluster_id)):
        parser.error("Replay preserves identity and observation time from the snapshot")
    run_id = utc_timestamp().replace(":", "").replace(".", "-") + "-" + uuid.uuid4().hex[:8]
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"run_id": run_id, "mode": "replay" if args.replay else "live",
                "started_at": utc_timestamp(), "status": "failed", "record_count": 0,
                "collector_version": API_COLLECTOR_VERSION}
    try:
        if args.replay:
            snapshot = json.loads(args.replay.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                raise CollectorError("Snapshot must be an object")
        else:
            header = snapshot_header(args.source, args.target, args.company_id, args.company_name,
                                     origin_cluster_id=args.origin_cluster_id)
            if args.source == "lever":
                collector = LeverCollector(region=args.region, max_pages=args.max_pages)
            elif args.source == "github":
                collector = GitHubCollector(window_days=args.window_days, max_pages=args.max_pages)
            else:
                collector = COLLECTORS[args.source]()
            snapshot = collector.collect(HttpClient(token=os.environ.get("GITHUB_TOKEN")), header)
        records = normalize(snapshot)
        write_json(run_dir / "snapshot.json", snapshot)
        staged = run_dir / "records.jsonl.tmp"
        staged.write_text("".join(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
                                  for record in records), encoding="utf-8")
        staged.replace(run_dir / "records.jsonl")
        manifest.update(status="success", source=snapshot["source"], target=snapshot["target"],
                        company_id=snapshot["company_id"], observed_at=snapshot["observed_at"],
                        record_count=len(records), coverage=snapshot.get("coverage", {}))
    except (CollectorError, ValidationError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Avoid logging response bodies or credentials.
        manifest.update(error_type=type(exc).__name__,
                        error=str(exc) if isinstance(exc, CollectorError) else "Invalid snapshot or output I/O failure")
    finally:
        manifest["finished_at"] = utc_timestamp()
        write_json(run_dir / "manifest.json", manifest)
    print(json.dumps({"status": manifest["status"], "record_count": manifest["record_count"],
                      "manifest": str(run_dir / "manifest.json")}))
    if manifest["status"] != "success":
        print(manifest["error"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
