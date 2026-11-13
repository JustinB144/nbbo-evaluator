# DECISIONS (the short version for this file; the full list with dates and reasons is docs/DECISIONS.md):
#     -Locked and crossed quotes were kept out of taker_pnl (the ask0 <= bid0 line in compute_outcomes)
#     -Days with no usable IC (fewer than 2 active rows, or all scores equal) are skipped and counted
#     -p-values are two-sided; the t keeps the sign. A negative score is a short, so IC > 0 means
#      the calls are right, shorts included. Multiple testing is FDR, applied later from the ledger's
#      raw p-values by a separate review step, not here (SPEC Part 5, S1-1 to S1-3)
#     -Stage 1 level: 15%
#     -IC is Spearman with average ranks (study S0003); p-values and 90% CIs use the Student t-distribution
#     -Refuses if the card or this file has uncommitted changes; the ledger row is written last, every accepted run
#     -Quotes are loaded one day at a time (memory: 2 GB instead of 15 GB on 20 days)


import argparse
import csv
import json
import math
import subprocess
import sys
import tomllib
import uuid
from datetime import datetime
from pathlib import Path

import duckdb

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
CI_LEVEL = 0.90    # confidence intervals match the 15% level: p < 0.10 exactly when the 90% CI excludes 0

# The ledger's columns, in file order (SPEC Part 4). A change here is a spec
# change: append_ledger refuses a ledger whose header doesn't match.
LEDGER_COLUMNS = (
    "run_id", "run_time", "code_commit",
    "question_id", "version", "variant", "split", "latency_ms",
    "n_rows", "n_active", "n_days", "n_symbols",
    "no_quote", "after_close", "n_trades", "skipped_days",
    "ic_mean", "ic_t", "ic_p", "ic_ci_low", "ic_ci_high", "ic_by_condition", "ic_at_0ms",
    "taker_bps_per_trade", "hit_rate", "taker_t", "taker_p", "taker_ci_low", "taker_ci_high",
    "max_corr_to_passed", "trials_all", "trials_question", "note")

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
    try:
        readf = con.read_parquet(args.input_file)
    except duckdb.Error as e:
        print(f"refused: {args.input_file} is not a readable Parquet stream ({e})")
        sys.exit(1)
    if list(readf.columns) != list(COLUMN_CONST):
        print(f"refused: columns are {list(readf.columns)}, must be exactly {list(COLUMN_CONST)}")
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
        check=False, capture_output=True, text=True)
    if last_commit.returncode != 0 or last_commit.stdout.strip() == "":
        print(f"refused: {card_path} has never been committed")
        sys.exit(1)

    # Unchanged: git status prints one line per file that differs from its last
    # commit. Checked for the card AND this program, so every ledger row's
    # code_commit is exactly the code that ran.
    changes = subprocess.run(["git", "status", "--porcelain", "--", str(card_path), "evaluate.py"],
        check=False, capture_output=True, text=True)
    if changes.returncode != 0 or changes.stdout.strip() != "":
        print(f"refused: uncommitted changes (commit them, then run again):\n{changes.stdout}")
        sys.exit(1)

    print(f"accepted: {label['question_id']} v{label['version']} {label['variant']}, card {card_path}")
    return label, card_path


# Runs once. Makes the table `stream` in con and returns the card's latency in
# nanoseconds and the sorted list of days the stream covers.
def load_inputs(args, con, card_path):
    with open(card_path, "rb") as f:
        card = tomllib.load(f)
    latency_ns = card["latency_ms"] * 1_000_000

    con.execute("CREATE TABLE stream AS SELECT * FROM read_parquet(?)", [args.input_file])

    # fetchall() gives a list of tuples, one per row: [(day,), (day,), ...]
    days = [r[0] for r in con.execute("SELECT DISTINCT day FROM stream ORDER BY day").fetchall()]
    if not days:
        print("refused: the stream has no rows")
        sys.exit(1)
    missing = [d for d in days if not Path(f"{NBBO_DIR}/{d}.parquet").exists()]
    if missing:
        print(f"failed: no NBBO file for {missing}; run scripts/build_nbbo.py")
        sys.exit(1)

    # Quotes are NOT loaded here. All days at once costs memory in proportion
    # to the number of days (14 GB for 20 days, measured in A2); compute_outcomes
    # reads one day at a time instead.
    return latency_ns, days


# Step 3b. Called twice: with the card's latency, then with 0.
# Makes (or replaces) the table `outcomes` and returns the drop counts.
# Works one day at a time: load that day's quotes, join that day's stream rows
# to them, add the result to `outcomes`. Memory then depends on the busiest
# single day (about 1.4 GB peak), not on how many days the stream covers.
# Each NBBO file holds one day, so the join only needs to match the symbol.
def compute_outcomes(con, latency_ns, days):
    for i, day in enumerate(days):
        con.execute("""CREATE OR REPLACE TEMP TABLE day_quotes AS
            SELECT symbol, nanos,
                arg_max(bid, file_row_number) AS bid,
                arg_max(ask, file_row_number) AS ask
            FROM read_parquet(?, file_row_number = true)
            GROUP BY symbol, nanos""", [f"{NBBO_DIR}/{day}.parquet"])
        # The first day creates `outcomes` (replacing the previous call's);
        # every later day adds its rows to it.
        start = "CREATE OR REPLACE TABLE outcomes AS" if i == 0 else "INSERT INTO outcomes"
        con.execute(start + """
        WITH s AS (
            SELECT *,
                event_time + ? AS t0,
                event_time + ? + horizon_ns AS t1
            FROM stream
            WHERE day = ?
        ),
        j AS (
            SELECT s.*,
                q0.bid AS bid0, q0.ask AS ask0,
                q1.bid AS bid1, q1.ask AS ask1
            FROM s
            ASOF LEFT JOIN day_quotes q0
                ON s.symbol = q0.symbol AND s.t0 >= q0.nanos
            ASOF LEFT JOIN day_quotes q1
                ON s.symbol = q1.symbol AND s.t1 >= q1.nanos
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
            [latency_ns, latency_ns, day])
    con.execute("DROP TABLE day_quotes")

    after_close, no_quote = con.execute("SELECT count_if(t1 > ? AND bid0 IS NOT NULL), count_if(bid0 IS NULL) FROM outcomes",[CLOSE_NS]).fetchone()
    con.execute("DELETE FROM outcomes WHERE t1 > ? OR bid0 IS NULL",[CLOSE_NS])

    return no_quote, after_close


# Step 3c, the IC part. Reads `outcomes` (active rows only).
# `group` is pasted into the SQL: a column name such as "condition_state" gives
# one result row per state; the constant "'all'" puts every row in one group.
# Returns a list of rows: (group, ic_mean, ic_t, ic_days, skipped_days, ic_se).
# Spearman = Pearson corr() of average ranks. Average rank: number the rows
# 1, 2, 3, ... in order, then give every tied value the mean of its numbers.
def compute_ic(con, group):
    return con.execute(f"""
        WITH numbered AS (
            SELECT day, {group} AS grp, score, mid_move,
                row_number() OVER (PARTITION BY day, {group} ORDER BY score)    AS rn_score,
                row_number() OVER (PARTITION BY day, {group} ORDER BY mid_move) AS rn_move
            FROM outcomes
            WHERE active
        ),
        ranked AS (
            SELECT day, grp,
                avg(rn_score) OVER (PARTITION BY day, grp, score)    AS score_rank,
                avg(rn_move)  OVER (PARTITION BY day, grp, mid_move) AS move_rank
            FROM numbered
        ),
        daily AS (
            SELECT day, grp,
                CASE WHEN isnan(corr(score_rank, move_rank)) THEN NULL
                    ELSE corr(score_rank, move_rank) END AS ic
            FROM ranked
            GROUP BY day, grp
        )
        SELECT grp,
            avg(ic)                                       AS ic_mean,
            avg(ic) / (stddev_samp(ic) / sqrt(count(ic))) AS ic_t,
            count(ic)                                     AS ic_days,
            count_if(ic IS NULL)                          AS skipped_days,
            stddev_samp(ic) / sqrt(count(ic))             AS ic_se
        FROM daily
        GROUP BY grp
        ORDER BY grp
        """).fetchall()

# Step 3c, the taker part. Reads `outcomes`. A trade is a row with a taker_pnl
# (active, score not 0, quote not crossed or locked).
def trade_summary(con):
    # Over every trade.
    taker_bps_per_trade, hit_rate, n_trades = con.execute("""
        SELECT avg(taker_pnl),
            count_if(taker_pnl > 0) / count(taker_pnl),
            count(taker_pnl)
        FROM outcomes
        """).fetchone()

    # From one mean per day, the same way as ic_t.
    taker_day_mean, taker_t, taker_se, taker_days = con.execute("""
        WITH daily AS (
            SELECT day, avg(taker_pnl) AS day_pnl
            FROM outcomes
            GROUP BY day
        )
        SELECT avg(day_pnl),
            avg(day_pnl) / (stddev_samp(day_pnl) / sqrt(count(day_pnl))),
            stddev_samp(day_pnl) / sqrt(count(day_pnl)),
            count(day_pnl)
        FROM daily
        """).fetchone()

    return taker_bps_per_trade, hit_rate, n_trades, taker_day_mean, taker_t, taker_se, taker_days


# How much evidence the stream submitted, counted before any row is dropped.
def evidence_counts(con):
    n_rows, n_active, n_days, n_symbols = con.execute("""
        SELECT count(*), count_if(active), count(DISTINCT day), count(DISTINCT symbol)
        FROM stream
        """).fetchone()
    return n_rows, n_active, n_days, n_symbols


# Counts ledger rows so far. Both counts include this run (+ 1).
def ledger_trials(ledger_path, qid):
    rows = []
    if Path(ledger_path).exists():
        with open(ledger_path, newline="") as f:
            rows = list(csv.DictReader(f))      # list of dicts, one per row, keyed by column name
    n_all = len(rows) + 1
    n_this = sum(1 for r in rows if r["question_id"] == qid) + 1
    return n_all, n_this


# Regularized incomplete beta I_x(a, b), by its continued fraction (Lentz's
# method). Only used by t_p below: the Student t-distribution's tail area is one.
def incomplete_beta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):            # the fraction converges fast only on this side
        return 1 - incomplete_beta(b, a, 1 - x)
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1 - x)) / a
    tiny = 1e-300
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    f = d
    for m in range(1, 300):
        for num in (m * (b - m) * x / ((a + 2*m - 1) * (a + 2*m)),
                    -(a + m) * (a + b + m) * x / ((a + 2*m) * (a + 2*m + 1))):
            d = 1 + num * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + num / c
            c = c if abs(c) > tiny else tiny
            f *= c * d
        if abs(c * d - 1) < 1e-15:
            break
    return front * f


# Two-sided p-value of t under the Student t-distribution with df degrees of
# freedom: the area beyond |t| on both sides. With few days the t-distribution
# has fatter tails than the bell curve, so this p is larger (honest) where the
# bell curve's would be too small.
def t_p(t, df):
    return incomplete_beta(df / 2, 0.5, df / (df + t * t))


# The t whose two-sided p is 1 - level (level 0.90 -> 5% in each tail), found by
# halving the interval [0, 1000] until it is tiny.
def t_critical(level, df):
    lo, hi = 0.0, 1000.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if t_p(mid, df) > 1 - level:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# From a mean of per-day values, its standard error and the number of days:
# the two-sided p-value (null: the true mean is 0) and the CI_LEVEL confidence
# interval, both from the t-distribution with days - 1 degrees of freedom.
# The sign is not in p, so read it from the mean: a small p with a negative mean
# is evidence against the prediction, not for it.
def inference(mean, se, days):
    if mean is None or se is None or days < 2:     # one day: no std, so no t
        return None, None, None
    if se == 0:                                    # every day identical
        return (0.0 if mean != 0 else 1.0), mean, mean
    half = t_critical(CI_LEVEL, days - 1) * se
    return t_p(mean / se, days - 1), mean - half, mean + half

# Step 3d. Appends one row to the ledger. Never rewrites existing rows. The
# identity columns are filled here; `row` holds everything else.
def append_ledger(ledger_path, row):
    commit = subprocess.run(["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
    if commit.returncode != 0:
        print("failed: git rev-parse HEAD did not work; nothing written")
        sys.exit(1)
    row = {"run_id": uuid.uuid4().hex,
           "run_time": datetime.now().astimezone().isoformat(timespec="seconds"),
           "code_commit": commit.stdout.strip(),
           **row}                                   # ** copies every key/value of row into this dict

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)  # makes ledger/ if missing; no-op if it exists
    new_file = not path.exists()
    if not new_file:
        # The header is the first line. If it isn't LEDGER_COLUMNS, appending
        # would put values under the wrong column names.
        with open(path, newline="") as f:
            header = next(csv.reader(f), [])
        if tuple(header) != LEDGER_COLUMNS:
            print(f"refused: {path} header doesn't match LEDGER_COLUMNS; nothing written")
            sys.exit(1)

    with open(path, "a", newline="") as f:          # "a" = append: add to the end, never overwrite
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)                        # None becomes an empty cell
    print(f"ledger: appended run {row['run_id']} to {path}")


def main():
    args = flags()
    con = duckdb.connect()
    label, card_path = refusals(args, con)
    latency_ns, days = load_inputs(args, con, card_path)
    n_rows, n_active, n_days, n_symbols = evidence_counts(con)

    no_quote, after_close = compute_outcomes(con, latency_ns, days)
    _, ic_mean, ic_t, ic_days, skipped_days, ic_se = compute_ic(con, "'all'")[0]
    rows = compute_ic(con, "condition_state")
    ic_by_condition = json.dumps({row[0]: row[1] for row in rows})
    (taker_bps_per_trade, hit_rate, n_trades,
        taker_day_mean, taker_t, taker_se, taker_days) = trade_summary(con)
    n_all, n_this = ledger_trials(args.ledger, label["question_id"])
    ic_p, ic_ci_low, ic_ci_high = inference(ic_mean, ic_se, ic_days)
    taker_p, taker_ci_low, taker_ci_high = inference(taker_day_mean, taker_se, taker_days)
    print(f"latency {latency_ns // 1_000_000} ms: ic_mean {ic_mean}, ic_t {ic_t}, "
        f"{ic_days} days, {skipped_days} skipped; dropped {no_quote} no quote, {after_close} after close")
    print(f"  ic_p {ic_p}, {CI_LEVEL:.0%} CI [{ic_ci_low}, {ic_ci_high}]")
    print(f"  by condition {ic_by_condition}")
    print(f"  taker {taker_bps_per_trade} bps/trade, hit rate {hit_rate}, taker_t {taker_t}, {n_trades} trades")
    print(f"  taker_p {taker_p}, {CI_LEVEL:.0%} CI of the daily mean [{taker_ci_low}, {taker_ci_high}]")
    print(f"  trials {n_all} all-time, {n_this} this question")

    compute_outcomes(con, 0, days)    # the drop counts at 0 ms are not needed
    ic_at_0ms = compute_ic(con, "'all'")[0][1]
    print(f"latency 0 ms: ic_mean {ic_at_0ms}")

    # 3d: everything is computed, so the write is the last step. If anything
    # above failed, the program stopped before this line and nothing was written.
    append_ledger(args.ledger, {
        "question_id": label["question_id"], "version": label["version"],
        "variant": label["variant"], "split": args.split, "latency_ms": latency_ns // 1_000_000,
        "n_rows": n_rows, "n_active": n_active, "n_days": n_days, "n_symbols": n_symbols,
        "no_quote": no_quote, "after_close": after_close, "n_trades": n_trades,
        "skipped_days": skipped_days,
        "ic_mean": ic_mean, "ic_t": ic_t, "ic_p": ic_p,
        "ic_ci_low": ic_ci_low, "ic_ci_high": ic_ci_high,
        "ic_by_condition": ic_by_condition, "ic_at_0ms": ic_at_0ms,
        "taker_bps_per_trade": taker_bps_per_trade, "hit_rate": hit_rate,
        "taker_t": taker_t, "taker_p": taker_p,
        "taker_ci_low": taker_ci_low, "taker_ci_high": taker_ci_high,
        "max_corr_to_passed": None,                 # SPEC: left empty for now
        "trials_all": n_all, "trials_question": n_this,
        "note": ""})


if __name__ == "__main__":
    main()
