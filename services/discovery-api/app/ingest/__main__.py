"""``python -m app.ingest``: build a product subset from ESCI-shaped files. Dry run unless --out is given."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ingest.models import ProductProvenance
from app.ingest.pipeline import IngestError, ingest, verify_subset, write_subset

ESCI_CITATION = "Reddy et al., Shopping Queries Dataset, 2022, arXiv:2206.06588"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="select, validate and (with --out) write a subset")
    build.add_argument("--products", type=Path, required=True)
    build.add_argument("--examples", type=Path, required=True)
    build.add_argument("--dataset-version", required=True, help="the version or download date you recorded")
    build.add_argument("--locale", default="us")
    build.add_argument("--limit", type=int, default=25000)
    build.add_argument("--seed", type=int, default=7)
    build.add_argument("--out", type=Path, help="new directory to write into; omit for a dry run")
    check = sub.add_parser("verify", help="confirm a written subset still matches its manifest")
    check.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "verify":
            manifest = verify_subset(args.out)
            print(f"ok selected={manifest.selected} checksum={manifest.subset_checksum[:12]}")
            return 0
        provenance = ProductProvenance(
            dataset="esci", dataset_version=args.dataset_version, citation=ESCI_CITATION, synthetic=False
        )
        result = ingest(
            args.products, args.examples, provenance=provenance, locale=args.locale, limit=args.limit, seed=args.seed
        )
        m = result.manifest
        print(f"rows_read={m.rows_read} candidates={m.candidates} selected={m.selected} quarantined={m.quarantined}")
        if args.out is None:
            print("dry run: nothing written (pass --out DIR to write)")
            return 0
        write_subset(result, args.out)
        print(f"wrote {args.out} checksum={m.subset_checksum[:12]} license_status={m.provenance.license_status}")
        return 0
    except IngestError as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
