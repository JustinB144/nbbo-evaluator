import csv
from pathlib import Path
import subprocess


def main():
	with open("/mnt/data/artifacts/research_system/taq/2026-10-12-research-samples/out/assignment.csv") as f:
		days = [r["day"] for r in csv.DictReader(f) if r["horizon"] == "1s-1min" and (r["role"] == "test" or r["role"] == "validation")]

	built = 0
	skipped = 0
	failed = []
	for day in days:
		if Path("/mnt/data/artifacts/a1/nbbo", f"{day}.parquet").exists():
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


if __name__ == "__main__":
	main()
