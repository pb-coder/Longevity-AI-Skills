# Swim coaching cheat-sheet

Use this when the `/coach` JSON has a `swim_summary` block. When that key
is missing (no swims in the last 28 days, or the user is on an HL
tracker that doesn't carry lap data), don't write a swim section at
all — silence is correct.

## When to surface what

The `swim_summary` block is the single source for the swim section.
Read it and write a paragraph or two — not a per-session log.

- **No swim section** when `swim_summary` is absent. Don't speculate
  about swim form from `cardio_last_28d` swim minutes alone — without
  per-lap data the signal is too coarse.
- **Trend over absolute** is the rule. The user's own SPL of 7.5 / 25m
  isn't "good" or "bad" by itself; what matters is whether it's
  trending down at constant pace (technique improving), trending up
  (fatigue / form breakdown), or flat. Cite the trend slope.
- **Lead with what changed.** If `swim_summary.spl_trend_4w_per_week`
  is negative (SPL falling) and pace is steady or improving, that's
  the headline. Open with it.

## SWOLF benchmarks (25m pool)

SWOLF = stroke count + seconds for one length. Lower is better. Rough
ability bands (sourced from
[Train Daly](https://www.traindaly.com/train-daly/blog/swolf-in-swimming-how-to-calculate-it)):

| SWOLF | Bracket |
|---|---|
| < 35 | Elite |
| 35–45 | Excellent |
| 46–55 | Good |
| 56–70 | Average |
| > 70 | Needs work |

Don't quote the absolute bracket unless the user asked. Use it as
internal context for sanity-checking; otherwise cite trend.

## SPL targets (per 25m length)

Strokes-per-length scales with height + technique. Typical ranges:

- 6'+ (183 cm+) competitive freestyle: 12–16
- 5'8"–6' (173–183 cm) recreational freestyle: 16–22
- Beginner / easy aerobic: 22–30

Again — trend matters more than the absolute. A user dropping from 24
to 18 over 4 weeks at constant pace is a strong technique improvement
signal regardless of where 18 sits on the bracket.

## CSS zones

CSS = Critical Swim Speed pace, in seconds per 100m. Sourced from a
400m + 200m TT pair via `(t400_sec - t200_sec) / 2` (per
[MyProCoach](https://www.myprocoach.net/calculators/critical-swim-speed/),
[TopEndSports](https://www.topendsports.com/testing/tests/critical-swim-speed.htm)).

Zone classification (lower sec/100m = faster, so "below CSS" means
faster than threshold):

| Zone | Pace vs CSS | Use |
|---|---|---|
| Recovery | > 110% CSS | Easy aerobic; warmup, cooldown, recovery sets |
| Aerobic | 100–110% CSS | Endurance base; long sets |
| Threshold | 90–100% CSS | CSS work; main set |
| VO2 | < 90% CSS | Speed; short reps with full recovery |

When `swim_summary.css_zone_distribution` is present, read it: a
healthy 4-week mix is roughly 60% Recovery+Aerobic / 30% Threshold /
10% VO2. Pure threshold-grinding (most sessions in Threshold) without
recovery work is a flag for accumulating fatigue.

When CSS is missing (`swim_summary.css` is null), skip zone language
entirely and prompt the user to run a CSS test once they're ready.

## CSS retest cadence

`swim_summary.css_retest_due` is True when the stored CSS is missing
or set more than 56 days ago, AND the user has at least 4 swims in
the past 28 days. Per
[North Endurance](https://www.northendurance.co.uk/critical-swim-speed),
CSS drifts as fitness changes — retest every 6–8 weeks during active
swim training. When the flag is True, prompt the user with the
explicit `CSS test` workflow:

> Log a 400m + 200m TT pair on the same day with `CSS test` on the
> header line. The logger will compute and write CSS to your profile.

## Trend interpretation

Translate the slopes / per-week trends from `swim_summary` into a
narrative:

- **Falling SWOLF + steady or rising pace** → technique / fitness
  improving. The cleanest positive signal in swimming.
- **Falling SPL at constant pace** → improving distance per stroke.
  Often pairs with a falling SWOLF.
- **Rising SWOLF at constant pace** → fatigue accumulating. If
  training load is high (`training_load.tsb` deeply negative), suggest
  a reduced swim volume week.
- **Rising SPL + falling pace** → form breakdown. Often shows up
  late in long sessions or after a load spike.
- **Stroke-mix outliers** (`stroke_outliers`) → almost always Apple
  Watch misclassification (a freestyle session with one "Butterfly"
  lap, etc.). Flag for the user to verify; never treat as a real
  stroke change without confirmation.

## CSS test detection

If `swim_summary.css_test_detected` is non-null, the user logged a
400m + 200m pair recently but didn't tag it `CSS test`. The coach
should ask:

> Looks like you did a 400m + 200m pair on YYYY-MM-DD — was that a
> CSS test? If yes, the inferred CSS is X sec/100m. Want me to write
> that to your profile? You can re-log with `CSS test` on the header.

Don't auto-write — only the explicit `CSS test` keyword on `/log`
triggers the profile update.

## What NOT to say

- Don't lecture about technique (catch, body roll, kick mechanics).
  The coach reads metrics, not video. Point to trend; let the user
  own technique work.
- Don't compare to elite benchmarks unless the user asked. Most users
  swim recreationally; benchmarking against 6'2" 0:55/100m collegiate
  freestylers demoralises rather than informs.
- Don't quote stroke counts down to the decimal in the user-facing
  text. SPL "around 18" beats "SPL=18.27" — the precision is fake at
  the human level.
- Don't treat per-lap stroke outliers as real until the user
  confirms. Apple Watch swim classification gets confused on flip
  turns and stroke transitions; one "Butterfly" lap in a freestyle
  session is almost always noise.
