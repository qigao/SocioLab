# Fictional repeat-interaction cases

Generate a fresh directory with `python examples/repeat-interaction/generate_fixture.py /path/to/fictional-case`.
The generator uses the real source importer. It writes no fitted model and
fetches no data. All four people, events, source times, membership and coverage
declarations are invented; all target outcomes are authored in advance.

History is `[0,20)`, recent history `[15,20)`, target `[20,30)`. The actual
history cutoff is **K17**. The three ordered risk pairs are A→B (three history
events, one recent), A→C (one history event, none recent), and B→D (two history
events, one recent). Both the event at history start 0 and recent start 15 count.

| Scenario | K | Expected scoring |
| --- | ---: | --- |
| `complete` | 21 | Three scorable pairs: A→B and B→D positive, A→C negative. A→B at 30 is outside the target; at 20 is included. |
| `incomplete.target.json` with `partial.events.json` | 23 | Follow-up ends at 23: all pairs unscored, two known positive pairs; the already-received event at 24 is not selected. |
| `partial` | 23 | Only A→B scorable. A→C has a coverage gap; B→D lacks full-horizon membership. Both retain known positives without contributing to any model's score. |
| `restored` | 24 | Coverage for C is restored over `[25,30)`: A→B and A→C are scorable positives; B→D remains unscored. |
| `retracted` | 25 | A→C's target event is retracted: two scorable pairs, one positive and one negative. The prediction is unchanged. |

The complete and partial scenarios are separate authored branches of the same
history, not successive versions of one realized future. The restored and
retracted cases append to the partial branch. Replaying K17 predictions and
the K23 partial score after those appends must reproduce their original bytes.

An independent cooperation declaration A–B stays active at source tick 40 even
when the complete communication window `[31,40)` is empty. Appending a distinct
`relation.changed` zero at tick 35 creates `terminated.events.json` (K22 on the
complete branch), removing that state edge. Window expiry alone does not do so.
Complete-branch communication coverage extends through 40 expressly for this
comparison; cooperation coverage is open-ended.

The documented create/score commands use the generated `history.events.json`,
`specification.json`, `complete.events.json`/`complete.target.json`, and
`partial.events.json`/`partial.target.json`. Forecasts and snapshots contain
pair-level source data and belong in private outputs. The execution evidence
under `docs/experiments/2026-11-28-repeat-interaction/` publishes only aggregate
scenario results and integrity hashes. It validates software behavior, not real
population coverage, probability calibration, predictive performance or causes.
