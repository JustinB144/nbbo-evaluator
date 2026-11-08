import argparse
import duckdb
import sys
import json
import subprocess
import tomllib
from pathlib import Path

# Constants at the top of the file can be read by every function below.
COLUMN_CONST = (
    "day",
    "symbol",
    "event_time",
    "available_time",
    "horizon_ns",
    "score",
    "active",
    "condition_state")
SPLIT_FILE = "/mnt/data/artifacts/research_system/taq/2026-10-12-research-samples/out/assignment.csv"
NBBO_DIR = "/mnt/data/artifacts/a1/nbbo"
CLOSE_NS = 16 * 3600 * 1_000_000_000

# Reads the command line and returns it.
def flags():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", type=str,
        help="Input file name")
    parser.add_argument("--split",
        default = "test",
        choices = ["validation", "test"],
        help = "Default is 'test' only use flag for validation runs")
    parser.add_argument("--ledger", type=str,
        default = "ledger/ledger.csv",
        help = "Default is ledger/ledger.csv, put in preffered ledger path to change it")
    return parser.parse_args()


# Step 3a. Exits with 1 if the stream breaks a rule. Otherwise returns the
# stream's label (from its .json) and the path of its card.
def refusals(args, con):
    readf = con.read_parquet(args.input_file)
    if list(readf.columns) != list(COLUMN_CONST):
        print(f"refused: Missing columns")
        sys.exit(1)

    n = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE available_time > event_time",
        [args.input_file],).fetchone()[0]
    if n > 0:
        print(f"refused: {n} rows have available_time > event_time")
        sys.exit(1)

    null_ct = con.execute("""
        SELECT count(*)
        FROM read_parquet(?)
        WHERE day IS NULL OR symbol IS NULL OR event_time IS NULL OR
            available_time IS NULL OR horizon_ns IS NULL OR score IS NULL OR
            active IS NULL OR condition_state IS NULL
        """,
        [args.input_file],).fetchone()[0]
    if null_ct > 0:
        print(f"refused: {null_ct} rows are NULL")
        sys.exit(1)

    duplicate_ct = con.execute("""
        SELECT count(*) FROM(
            SELECT day, symbol, event_time
            FROM read_parquet(?)
            GROUP BY day, symbol, event_time
            HAVING count(*) > 1
        )""",
        [args.input_file],).fetchone()[0]
    if duplicate_ct > 0:
        print(f"refused: {duplicate_ct} duplicated keys for day, symbol, or event time")
        sys.exit(1)

    big_horizon_ct = con.execute("""
        SELECT count(*)
        FROM read_parquet(?)
        WHERE horizon_ns > 60_000_000_000
        """,
        [args.input_file],).fetchone()[0]
    if big_horizon_ct > 0:
        print(f"refused: {big_horizon_ct} rows have horizons over 60s")
        sys.exit(1)

    small_horizon_ct = con.execute("""
        SELECT count(*)
        FROM read_parquet(?)
        WHERE horizon_ns < 1_000_000_000
        """,
        [args.input_file],).fetchone()[0]
    if small_horizon_ct > 0:
        print(f"refused: {small_horizon_ct} rows have horizons under 1s")
        sys.exit(1)

    missing_split_days = con.execute("""
        SELECT count(*)
        FROM read_parquet(?)
        WHERE day NOT IN(
            SELECT day
            FROM read_csv(?)
            WHERE role = (?) AND horizon = '1s-1min'
        )""",
        [args.input_file, SPLIT_FILE, args.split]).fetchone()[0]
    if missing_split_days > 0:
        print(f"refused: {missing_split_days} rows not allowed in the split")
        sys.exit(1)

    # The card: stream -> <variant>.json next to it -> question_id -> questions/<id>_*/card.toml
    json_path = Path(args.input_file).with_suffix(".json")
    if not json_path.exists():
        print(f"refused: no {json_path} next to the stream")
        sys.exit(1)
    with open(json_path) as f:
        label = json.load(f)
    for key in ["question_id", "version", "variant"]:
        if key not in label:
            print(f"refused: {json_path} has no {key}")
            sys.exit(1)

    cards = list(Path("questions").glob(f"{label['question_id']}_*/card.toml"))
    if len(cards) != 1:
        print(f"refused: expected 1 card for {label['question_id']}, found {len(cards)}")
        sys.exit(1)
    card_path = cards[0]

    # Committed: git log prints the last commit that touched the card, or nothing if none did.
    last_commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", str(card_path)],
        capture_output=True, text=True)
    if last_commit.returncode != 0 or last_commit.stdout.strip() == "":
        print(f"refused: {card_path} has never been committed")
        sys.exit(1)

    # Unchanged: git status prints a line if the card differs from its last commit.
    changes = subprocess.run(["git", "status", "--porcelain", "--", str(card_path)],
        capture_output=True, text=True)
    if changes.returncode != 0 or changes.stdout.strip() != "":
        print(f"refused: {card_path} has uncommitted changes")
        sys.exit(1)

    print(f"accepted: {label['question_id']} v{label['version']} {label['variant']}, card {card_path}")
    return label, card_path


# Runs once. Makes two tables in con, `stream` and `quotes`, and returns the
# card's latency in nanoseconds.
def load_inputs(args, con, card_path):
    with open(card_path, "rb") as f:
        card = tomllib.load(f)
    latency_ns = card["latency_ms"] * 1_000_000

    con.execute("CREATE TABLE stream AS SELECT * FROM read_parquet(?)", [args.input_file])

    # fetchall() gives a list of tuples, one per row: [(day,), (day,), ...]
    days = [r[0] for r in con.execute("SELECT DISTINCT day FROM stream").fetchall()]
    paths = [f"{NBBO_DIR}/{day}.parquet" for day in days]
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        print(f"failed: no NBBO file for {missing}; run scripts/build_nbbo.py")
        sys.exit(1)

    # r"""...""" (raw string) so the \d in the pattern reaches DuckDB unchanged.
    con.execute(r"""
        CREATE TABLE quotes AS
        SELECT CAST(regexp_extract(filename, '(\d{4}-\d{2}-\d{2})\.parquet', 1) AS DATE) AS day,
            symbol, nanos, bid, ask
        FROM read_parquet(?, filename = true)
        """, [paths])
    return latency_ns


# Step 3b. Called twice: with the card's latency, then with 0.
# Makes (or replaces) the table `outcomes` and returns the drop counts.
def compute_outcomes(con, latency_ns):
    con.execute("""
        CREATE OR REPLACE TABLE outcomes AS
        WITH s AS (
            SELECT *,
                event_time + ? AS t0,
                event_time + ? + horizon_ns AS t1
            FROM stream
        ),
        j AS (
            SELECT s.*,
                q0.bid AS bid0, q0.ask AS ask0,
                q1.bid AS bid1, q1.ask AS ask1
            FROM s
            ASOF LEFT JOIN quotes q0
                ON s.day = q0.day AND s.symbol = q0.symbol AND s.t0 >= q0.nanos
            ASOF LEFT JOIN quotes q1
                ON s.day = q1.day AND s.symbol = q1.symbol AND s.t1 >= q1.nanos
        )
        SELECT *,
            (bid0 + ask0) / 2 AS mid0,
            (bid1 + ask1) / 2 AS mid1,
            (mid1 - mid0) / mid0 * 10000 AS mid_move,
            CASE
                WHEN NOT active OR score = 0 THEN NULL
                WHEN ask0 <= bid0 THEN NULL               -- decision 1: crossed or locked at t0
                WHEN score > 0 THEN (mid1 - ask0) / mid0 * 10000
                ELSE                (bid0 - mid1) / mid0 * 10000
            END AS taker_pnl
        FROM j
        """,
        [latency_ns, latency_ns])
    
    after_close, no_quote = con.execute("SELECT count_if(t1 > ? AND bid0 IS NOT NULL), count_if(bid0 IS NULL) FROM outcomes",[CLOSE_NS]).fetchone()
    con.execute("DELETE FROM outcomes WHERE t1 > ? OR bid0 IS NULL",[CLOSE_NS])

    return no_quote, after_close


# Step 3c, the IC part. Reads `outcomes` (active rows only) and returns
# ic_mean, ic_t, the number of days with an IC, and the number of days skipped.
# Spearman = Pearson corr() of average ranks. Average rank: number the rows
# 1, 2, 3, ... in order, then give every tied value the mean of its numbers.
def compute_ic(con):
    ic_mean, ic_t, ic_days, skipped_days = con.execute("""
        WITH numbered AS (
            SELECT day, score, mid_move,
                row_number() OVER (PARTITION BY day ORDER BY score)    AS rn_score,
                row_number() OVER (PARTITION BY day ORDER BY mid_move) AS rn_move
            FROM outcomes
            WHERE active
        ),
        ranked AS (
            SELECT day,
                avg(rn_score) OVER (PARTITION BY day, score)    AS score_rank,
                avg(rn_move)  OVER (PARTITION BY day, mid_move) AS move_rank
            FROM numbered
        ),
        daily AS (
            SELECT day, corr(score_rank, move_rank) AS ic
            FROM ranked
            GROUP BY day
        )
        SELECT avg(ic)                                   AS ic_mean,
            avg(ic) / (stddev_samp(ic) / sqrt(count(ic))) AS ic_t,
            count(ic)                                    AS ic_days,
            count_if(ic IS NULL)                         AS skipped_days
        FROM daily
        """).fetchone()
    return ic_mean, ic_t, ic_days, skipped_days


def main():
    args = flags()
    con = duckdb.connect()
    label, card_path = refusals(args, con)
    latency_ns = load_inputs(args, con, card_path)

    no_quote, after_close = compute_outcomes(con, latency_ns)
    ic_mean, ic_t, ic_days, skipped_days = compute_ic(con)
    print(f"latency {latency_ns // 1_000_000} ms: ic_mean {ic_mean}, ic_t {ic_t}, "
        f"{ic_days} days, {skipped_days} skipped; dropped {no_quote} no quote, {after_close} after close")

    no_quote_0ms, after_close_0ms = compute_outcomes(con, 0)
    ic_at_0ms = compute_ic(con)[0]
    print(f"latency 0 ms: ic_mean {ic_at_0ms}")

    # 3d: write the ledger row


if __name__ == "__main__":
    main()
