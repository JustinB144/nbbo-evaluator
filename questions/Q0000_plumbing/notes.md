Results (scratch ledger, 20 quick-subset days)

┌──────────────────────┬────────────────┬──────────────────┬─────────────────────────────┐
│                      │    perfect     │     flipped      │          shuffled           │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ ic_at_0ms            │ 1.0            │ −1.0             │ −0.0002                     │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ ic_mean (250 ms)     │ 0.955          │ −0.955           │ 0.0005                      │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ ic_t                 │ 454.5          │ −454.5           │ 0.13                        │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ ic_p                 │ 8e-40          │ 8e-40            │ 0.90                        │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ IC 90% CI            │ [0.951, 0.959] │ [−0.959, −0.951] │ [−0.006, 0.007], contains 0 │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ taker bps/trade      │ +1.70          │ −6.52            │ −2.59                       │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ hit rate             │ 77%            │ 0.5%             │ 23%                         │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ trades               │ 32,188         │ 32,188           │ 32,269                      │
├──────────────────────┼────────────────┼──────────────────┼─────────────────────────────┤
│ skipped days / drops │ 0 / 0          │ 0 / 0            │ 0 / 0                       │
└──────────────────────┴────────────────┴──────────────────┴─────────────────────────────┘

What each check shows

- The joins and rank math are right. perfect at 0 ms gives an IC of exactly 1.0. The A2 tie problem didn't show up on these rows.
- The 250 ms latency is applied. The IC falls to 0.955 because the evaluator's window, 0.25 s to 10.25 s, isn't quite the planted window of 0 s to 10 s.
- The sign is never lost. flipped mirrors perfect exactly in the IC, t and CI. ic_p is the same for both, as a two-sided p must be.
- No signal is found in noise. shuffled has IC ≈ 0, p = 0.90, and a CI that straddles 0.

The taker numbers are right too

They look lopsided, but they shouldn't be mirror images.
- Every trade crosses the spread, whichever direction it bets. So perfect = move − cost, and flipped = −move − cost. Adding them leaves −2 × cost, so the cost is about 2.4 bps per trade.
- shuffled should then lose about one cost, and it does: −2.59 bps. A random direction earns nothing and still pays the spread.
- Its strongly negative taker_t (−3.2) is correct, not a false alarm. It's real evidence that random trading loses money.
- Its 23% hit rate is low because many 10 s mid moves are exactly 0, and a trade with zero move still loses the spread.
- About 32k of the 60k rows trade.
  - Rows with score 0 don't trade: the planted move was exactly 0.
  - Crossed or locked quotes at t0 don't trade either (decision 1).
  - shuffled has a slightly different count because its zero scores land on different rows.