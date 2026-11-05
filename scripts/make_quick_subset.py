import csv


def main(): 
	with open("/mnt/data/artifacts/research_system/taq/2026-10-12-research-samples/out/assignment.csv") as f:
		rows = [r for r in csv.DictReader(f) if r["horizon"] == "1s-1min" and r["role"] == "test"]
	rows = sorted(rows, key=lambda r: float(r["score"]))
	picked = [rows[round(i * 118 / 19)] for i in range (20)]
	with open("docs/quick_subset.csv", "w", newline="") as f:
		w = csv.DictWriter(f, fieldnames=["day", "score"])
		w.writeheader()
		for r in picked: 
			w.writerow({"day": r["day"], "score": r["score"]})

if __name__ == "__main__":
    main()