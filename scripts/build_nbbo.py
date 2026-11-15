import csv
from pathlib import Path
import subprocess
import json
import sys
from datetime import datetime

NBBO_DIR = Path("/mnt/data/artifacts/a1/nbbo")
SPLIT_FILE = "/mnt/data/artifacts/research_system/taq/2026-10-12-research-samples/out/assignment.csv"


def main():
    # build.json names the commit the files were built from, so that commit must
    # really hold the reader that runs: refuse if the reader's code has uncommitted
    # changes, and rebuild the binary from it first.
    changes = subprocess.run(["git", "status", "--porcelain", "--", "readers/", "foundation/"],
        check=False, capture_output=True, text=True)
    if changes.returncode != 0 or changes.stdout.strip() != "":
        print(f"refused: the reader has uncommitted changes (commit them, then run again):\n{changes.stdout}")
        sys.exit(1)
    if subprocess.run(["make", "build/read_nbbo"]).returncode != 0:
        print("failed: make build/read_nbbo did not work; nothing built")
        sys.exit(1)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
    if commit.returncode != 0:
        print("failed: git rev-parse HEAD did not work; nothing built")
        sys.exit(1)

    with open(SPLIT_FILE) as f:
        days = [r["day"] for r in csv.DictReader(f) if r["horizon"] == "1s-1min" and r["role"] == "test"]

    NBBO_DIR.mkdir(parents=True, exist_ok=True)
    built = 0
    skipped = 0
    failed = []
    for day in days:
        if (NBBO_DIR / f"{day}.parquet").exists():
            skipped += 1
            continue
        result = subprocess.run(["./build/read_nbbo", day], capture_output=True, text=True)
        if result.returncode != 0:
            failed.append(f"{day}: {result.stderr.strip()}")
        else:
            built += 1
            print("built", day)

    print("Days built:", built, "Days skipped:", skipped, "Days failed:", len(failed))
    for line in failed:
        print(line)

    # Only a complete build gets a record. With a failed day, fix it and run again:
    # the days already built are skipped.
    if failed:
        print("build.json not written: some days failed")
        sys.exit(1)
    record = {
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "code_commit": commit.stdout.strip(),
        "days": len(days),
    }
    with open(NBBO_DIR / "build.json", "w", encoding="utf-8") as file:
        json.dump(record, file, indent=4)
    print("wrote", NBBO_DIR / "build.json")


if __name__ == "__main__":
    main()
