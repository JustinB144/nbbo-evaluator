import argparse
import duckdb
import sys

def main():
    
    COLUMN_CONST = (
        "day",
        "symbol",
        "event_time",
        "available_time",
        "horizon_ns",
        "score",
        "active",
        "condition_state")
        
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
    args = parser.parse_args()

    con = duckdb.connect()

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
            FROM read_csv('/mnt/data/artifacts/research_system/taq/2026-10-12-research-samples/out/assignment.csv')
            WHERE role = (?) AND horizon = '1s-1min'
        )""",
        [args.input_file, args.split]).fetchone()[0]
    if missing_split_days > 0:
        print(f"refused: {missing_split_days} rows not allowed in the split")
        sys.exit(1)

    

if __name__ == "__main__":
    main()





























