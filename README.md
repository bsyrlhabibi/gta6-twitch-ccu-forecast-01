# gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/bsyrlhabibi/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/bsyrlhabibi/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

**Launch-day Twitch forecaster for Grand Theft Auto VI.** `main.py` (Python 3.13, standard library only) reads one case — everything known at the end of release day's first hour, plus 42 past big launches' hourly curves — and writes five quantiles (5/25/50/75/95%) of the Twitch viewer count for each of hours 2–24 of the UTC release day.

## The model

A similarity-weighted pool of past launches' release-day shapes:

1. **Shapes.** Each comparable launch contributes its release-day curve as log-ratios to its own first hour, r_k = ln(viewers_k / viewers_1), k = 1..23.
2. **Regime filter.** Two kinds of comparables are left out: the one that is not a launch (the GTA VI category's own pre-release history), and launches whose day peak exceeds e^3.5 ≈ 33× their first hour — simultaneous global unlocks in the middle of the UTC day, whose first hours are a pre-unlock trickle. A rolling midnight-local console launch never looks like that.
3. **Similarity weights.** The remaining launches are pooled per hour with Gaussian weights (bandwidths 0.6 on f2, 0.25 on g — retuned by leave-one-out for round 2; the tighter g bandwidth carries the gain) on two features known at the end of hour 1, computed identically for the case and for each comparable: **f2** = ln(mean viewers over the 6 hours before the day ÷ hour-1 viewers) and **g** = ln(last pre-day hour ÷ hour-1). A high f2 — hour 1 is a deep overnight trough for an already-warm category — goes with a steep day; a low f2 — hour 1 already at full blaze — goes with a flat one.
4. **Forecast.** q_tau(h) = p1 × exp(weighted quantile of the pooled r_h), with an empty-pool fallback to the persistence spread, and schema clamps (ordered, finite, within (0, 1e9]).

The program is deterministic (two runs byte-identical) and runs in ~0.2 s per case.

## Validation on the practice cases

Scored exactly as the contest scores — mean pinball loss on the log scale over hours 2–24 × 5 quantiles — against each practice launch's actual release-day curve (SullyGnome hourly averages, the same source the cases were built from; every fetched hour-1 print matches its case's known print):

| Case | Launch | This model | House persistence baseline |
| --- | --- | ---: | ---: |
| p00 | Marvel's Wolverine (2026-09-15) | 0.288 | 0.744 |
| p01 | Red Dead Redemption 2 (2018-10-26) | 0.197 | 0.287 |
| p02 | God of War Ragnarök (2022-11-09) | 0.151 | 0.215 |
| p03 | Marvel's Spider-Man 2 (2023-10-20) | 0.203 | 0.303 |
| **Mean** | | **0.210** | **0.387** |

Leave-one-out over the 29 pool launches (each forecast from the other 28) gives a mean loss of 0.285 for this model, against 0.310 for the same pool unweighted — the similarity weighting, not just the pool, is doing work. (Round 1, with bandwidths 0.35/0.45, scored 0.229 on the practice cases and 0.287 leave-one-out; the round-2 retune improves both.)

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` case in the input dir and writes one `<id>.out` per case to the output dir, each `{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]} …]}` for hours 2–24.

---

<sub>Entered on [make.fun](https://make.fun/?ref=v0n7q6s0&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
