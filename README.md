# nbbo-evaluator

Tools for testing short-horizon trading ideas on NYSE TAQ quote data: a C++ reader that turns a day of consolidated best quotes (NBBO) into clean Parquet, and a Python + DuckDB evaluator that scores a stream of forecasts against what the market actually did next.

The evaluator is the core idea. It refuses bad input instead of scoring it, it charges every forecast a realistic latency, and it was proven on planted signals before being trusted with real ones.

## What's here

| Path | What it does |
|---|---|
| `readers/read_nbbo.cpp` | One trading day of TAQ Complete NBBO → Parquet, 09:30–16:00, sorted by symbol then time. Handles the 2018 format change. Every dropped row is counted by reason (NULL / unparseable / zero price, bad time, missing symbol or size). Locked and crossed quotes are kept and counted, because they are real market states. |
| `evaluate.py` | Scores a forecast stream (Parquet: day, symbol, event time, score, horizon). See below. |
| `scripts/build_nbbo.py` | Builds the NBBO files for every test day. Refuses to run if the reader has uncommitted changes, rebuilds it, and records the commit it was built from. |
| `scripts/make_quick_subset.py` | Picks 20 days spread across a market-stress score, for quick first runs. |
| `questions/Q0000_plumbing/` | The planted-signal test of the evaluator (results below). |
| `foundation/` | Exact fixed-point prices and sizes (no floating point) and TAQ timestamps in nanoseconds, with each product's time resolution by date. Ported from my earlier `research_system` project, with Catch2 tests in `tests/`. |

## How the evaluator works

1. **Refusals first.** A stream is rejected, not scored, if it has look-ahead rows (data marked available after the event it's used for), NULLs, NaN or infinite scores, duplicate (day, symbol, time) keys, horizons outside 1–60 s, or days outside the allowed test split. Its question card must be committed, and its label must match the card's ID and version exactly.
2. **No silent re-runs.** Every run records a SHA-256 hash of its card. If a card is edited after it has been run, the evaluator refuses to run it again under the same version, so a test can't be quietly re-tuned until it passes. Only the plumbing test (Q0000) may write to a scratch ledger.
3. **Outcomes with latency.** For each forecast, DuckDB `ASOF` joins find the quote in force after the card's latency and the quote at the horizon. Quotes missing either the bid or the ask are never used. The outcome is the mid-price move between them, and a taker P&L that pays the spread.
4. **Information coefficient (IC).** Per day, a Spearman rank correlation between score and move, computed with SQL window functions and average ranks, so ties are handled correctly. Across days: mean IC, t-statistic, p-value and 90% confidence interval from the Student t distribution, computed in plain Python (no SciPy).
5. **Ledger.** Every accepted run appends one row, written last, so a crash never leaves a half-recorded result. Each row records the card hash, the stream hash, the quote-file build, and the DuckDB version, so any result can be traced back to exactly what produced it. A run where no rows survive still gets a row, so failed attempts are counted too.

## Planted-signal check (Q0000)

Before any real question, the evaluator was run on streams whose answer is known (20 days, about 60k rows):

| | perfect | flipped | shuffled |
|---|---|---|---|
| IC at 0 ms latency | 1.0 | −1.0 | −0.0002 |
| IC at 250 ms latency | 0.955 | −0.955 | 0.0005 |
| IC 90% CI | [0.951, 0.959] | [−0.959, −0.951] | [−0.006, 0.007] |
| taker bps / trade | +1.70 | −6.52 | −2.59 |

The joins and rank math are right (exactly 1.0 at zero latency), latency is applied (the IC drops when the window shifts), the sign is never lost (flipped mirrors perfect), and noise shows nothing. Shuffled loses about one spread per trade, as random trading should. Details are in `questions/Q0000_plumbing/notes.md`.

## Building

Linux, g++ with C++23, Python 3.11+ with `duckdb` (plus `numpy`/`scipy` for some studies).

```sh
# DuckDB's C++ header and shared library go in third_party/duckdb/ (see its README)
make          # reader + tests, built with AddressSanitizer and UBSan
make test
./build/read_nbbo 2019-05-03
```

**Data:** the TAQ files come from WRDS and can't be redistributed, so none are included. Paths to the raw data and output folders are set near the top of each file.

## Not included

The research questions themselves (signal ideas, their cards and results), the full design spec, and related studies are kept private. The comments that mention `SPEC.md`, `DECISIONS.md` or other question numbers refer to those.

## License

GPL-3.0. Catch2 (Boost Software License) and DuckDB (MIT) keep their own licenses.
