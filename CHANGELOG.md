# Changelog

## Unreleased

* **Ockenburg 1940** (eighth airhead member), sourced from War over Holland (read in full). The third Hague landing: 96 depot recruits not on alert, a one-platoon drop, 18 then 8 Ju 52 landing within the fight, the field German by 07:45. The Germans then moved off it (against Loosduinen, then into the woods under 12 cm howitzer fire), and two Grenadier companies and a recruit company retook a lightly held strip around 14:30. It reuses Valkenburg's mechanisms and `ctx.*` names (`redeploy:`, per-wave sizes), so the two can be context-swapped (added to the default `CPAIRS`); the Ypenburg-Ockenburg factor swap is added to `PAIRS`.
  * First anchor run (priors set before it): joint 0.14 (Lanchester), 0.39 (CRT); the recapture held in only 0.25 / 0.55 of runs.
  * One revision after that run, recorded in the parameter note: `response.commit_h` was 1-3 h, unsourced and set with only the first, failed company in mind; it applies to both counterattacks and made the decisive second assault give up while winning. Now Ypenburg's 8-14 h. Recapture 0.25 → 0.93; joint 0.20 (Lanchester), 0.47 (CRT).
  * The remaining miss is timing: the field is Dutch again after 14:30 in most Lanchester runs (`germans_off_field_by_1430` 0.23 / 0.50).
* **Waalhaven command values revised** after its first anchor run (parameter note). It had a battalion command cycle (decision every 1-2 h, lost contact, fog), which in this model means a commander who judges the situation and holds. The source describes the opposite: no telephone lines, the commander gone early, companies fleeing or surrendering on their own. Now no command cycle, as at Ypenburg. Joint 0.41 → 0.50 (Lanchester), 0.59 → 0.65 (CRT); median capture H+3.25 → H+2.75 (history H+1.6). The rest of the speed gap is attrition: the Dutch positions fell one by one in close combat and by an ordered surrender, which the model does not represent.
* **Context swaps** (`battlelab swap --context`, `battlelab report --context-pairs`, report section 3b). The `ctx.*` parameters two scenarios share become one more bundle, CONTEXT, in the full-factorial swap. This answers "how much of the difference is the setting", which the notes had flagged twice (Valkenburg, Waalhaven) as beyond an ordinary swap. Structure (zones, units, the number of waves) and context parameters only one scenario has are never swapped, so the CONTEXT share is a lower bound. `scripts/reproduce.sh` runs Ypenburg-Valkenburg and Ypenburg-Waalhaven by default (`CPAIRS`). Ordinary swaps are unchanged: a context swap's context-off corners reproduce them run for run (tested).
* `analysis.screen` returns an empty table instead of failing when the outcome is constant (it crashed `battlelab report` at small n).

## 0.6.0 (2026-10-10)

Seven scenarios: Waalhaven 1940 joins as the control for Ypenburg; Maleme's first-landing timing is fixed by a sourced daylight-confirmation rule (#5); Ypenburg's ammunition limit is sourced.

* **Waalhaven 1940** (seventh airhead member), sourced from War over Holland (read in full). The German success at the Rotterdam airfield on the same morning as Ypenburg, against a Jagers battalion: III./FJR 1 dropped behind the defence (about 50 Ju 52, 600 men), the first transports landed during the fight, the field was German by 06:30, and more than a thousand men were flown in on the first day. It shares Ypenburg's German side (RISK, AIR doctrine, mechanism constants), so the Ypenburg-Waalhaven swap (added to the default `PAIRS`) isolates what differed on the ground.
  * First anchor run, all priors set before it: joint 0.41 (Lanchester), 0.59 (CRT). Five of six anchors hold in at least 99% of runs. The miss is speed: the model takes the field at H+3.25 (median) against H+1.6 historically (`field_taken_fast` 0.42 / 0.59).
  * The test invariant on air-landed troops now uses the resolved (whole) aircraft count; Waalhaven's per-wave count is the first uniform draw where rounding mattered.
* **Ypenburg ammunition limit sourced** (`mass.ammo_out_h` 6-14 h → 6-10.5 h; WOH). At the truce of about 10:00-10:30 (H+6) the Germans redistributed their "scarce ammo". The field defence collapsed, with its ammunition caches exploding under Dutch artillery, shortly before the RAF raid at 15:10 (H+10.9). The range comes from that timeline, not from the anchors.
  * New anchor `germans_off_field_by_1510` (`attacker_hours_on_field` ≤ 11).
  * Joint share on the old anchors: 0.62 → 0.63 (Lanchester), 0.56 → 0.58 (CRT).
  * With the new anchor: 0.51 (Lanchester), 0.54 (CRT). The new anchor alone holds in 0.80 / 0.85 of runs, against 0.62 / 0.77 under the old range.
* **Daylight confirmation of control** (`airlift.commit_daylight`, RISK parameter `risk.commit_daylight`; issue #5). In shuttle mode, control gained at night (20:00-06:00) reaches the HQ only after the next dawn. Source: the 22nd Battalion left Point 107 overnight, and Student learnt of it only from a test landing at 08:10 on 21 May, then ordered II/100 to land from 16:00 (Long ch. 11). Default 0; Hostomel, Ypenburg and Valkenburg are identical run-for-run (300 runs each).
  * Maleme, Heraklion and Rethymno use it (same HQ). The decision cycle `risk.commit_cycle_h` it replaces is now 0 there. Keeping both delayed the commitment twice (first landing p50 H+35, P(airbridge) 0.63 → 0.25); this was seen in the first run, recorded in the parameter note, and the cycle was then set to 0.
  * Maleme: first landing p50 H+26.5 → H+31.8; `landings_begin_day2_afternoon` 0.19 → 0.56; joint 0.19 → 0.54 (Lanchester), 0.028 → 0.076 (CRT). Heraklion and Rethymno unchanged (within 0.001).

## 0.5.0 (2026-10-03)

Sourcing pass (issues #4, #5) against full texts instead of search excerpts: the NIMH airfield histories and the Hague WOH pages for Ypenburg and Valkenburg; Long, *Greece, Crete and Syria* (AWM official history, chapters 11-13) and Playfair, *Mediterranean and Middle East* vol. II for Crete. Every revised parameter note names its source.

* **Two mechanisms, each exactly the old model at its default** (Hostomel identical run-for-run over 2,000 runs under both resolvers; the wave sizes were checked on all six scenarios over 200 runs).
  * `airlift.wave_aircraft`: a separate aircraft count per wave.
  * `redeploy:`: a share of one side's troops leaves a zone it holds for another zone after a delay.
* **Valkenburg.** Sourced: two waves (53 and 5-12 aircraft), garrison 100-150, Dutch counterattacks at H+1-1.75 and H+11.5-12. The ammunition limit is off (1000 h): the German pocket held out to 14 May. With the sourced values alone the joint share fell to 0.002: the Germans held the field and never ran dry. The sources say most of them moved into Valkenburg village before the Dutch retook the field at 17:30, which the redeployment models (60-80% after 1-4 h, an assumption set before the anchor run). Joint 0.21 → 0.33 (Lanchester), 0.27 → 0.40 (CRT); retake 0.44 / 0.52.
* **Ypenburg.** Sourced: 40 aircraft per wave, sourced wave times, Dutch counterattacks at H+5.5-6 and H+7.5-10. Joint 0.63 → 0.62 (Lanchester), 0.61 → 0.56 (CRT).
* **Crete.** Garrison sizes and counterattack times from Long; Heraklion now uses the second counterattack (the Black Watch and Leicesters' sweeps); Rethymno's prisoners corrected to 25 + 34. Maleme's afternoon first-landing anchor is confirmed (troops air-landed about 16:00 on 21 May, H+32; one Ju 52 landed at 08:10). Joint shares under Lanchester / CRT:
  * Maleme 0.20 → 0.19 / 0.029 → 0.028
  * Heraklion 0.99 → 0.98 / 0.98 → 0.98
  * Rethymno 0.99 → 0.98 / 0.98 → 0.97
* Davin's NZ official history (NZETC) could not be read (the site blocks automated access); Long and Playfair cover the same events.


## 0.4.0 (2026-09-29)

Six scenarios, three new mechanisms for the Hague airfields, a garrison/command split of the defenders, and documentation for a public repository.

* **Docs:** `docs/MECHANISMS.md` (every mechanism: what it does, parameters, default, users) and `docs/PARAMETERS.md` (generated by the new `battlelab params`: every parameter across all scenarios with its provenance flag; a test keeps it current).

* **Airborne ammunition limit** (`mass.ammo_out_h`, MASS bundle; issue #13). Parachuted and air-landed units use the existing ammunition hazard. The value is 1000 h (not binding) in Hostomel, Maleme, Heraklion and Rethymno, which are identical run-for-run. Ypenburg and Valkenburg use 6-14 h, an assumption set before the anchor run.
  * Valkenburg: `dutch_retake_field` 0.07 → 0.29, joint 0.03 → 0.14.
  * Ypenburg: joint 0.54 → 0.62; with the sole-control anchor, 0.04 → 0.09.
* **Second, later counterattack** (`response.t_ca2`, `response.strength2`, RESPONSE bundle; issue #13). It is inactive (strength 0) outside the Hague scenarios. At Ypenburg and Valkenburg it comes at 8-14 h with 400-800 men, an assumption set before the anchor run.
  * Valkenburg: retake 0.29 → 0.41, joint 0.14 → 0.21 (Lanchester), which meets #13's targets.
  * Ypenburg: joint 0.62 → 0.63.
  * Also tried and not adopted: lower organisation for troops from bogged aircraft.
* **Valkenburg 1940** (sixth airhead member) and a **soft-ground mechanic**. With `airlift.bog_risk` (context parameter `ctx.bog_risk`), each landed aircraft may sink into soft ground: its troops get off, the aircraft stays on the strip as an obstacle, and it is counted in the new metric `transports_stranded`. The mechanic draws from its own random stream and makes no draw when off, so the other five scenarios are unchanged run-for-run (checked over 300 runs each).
  * Results: the Germans take the field in 56% of runs, and at least 20 transports are stranded in 40%. The Dutch retake the field in only 7%, so the joint share is 0.03. The counterattack cannot dislodge a few hundred landed troops; this is the same limit as Ypenburg.
  * The swap with Ypenburg is nearly silent, because what differed was the airfield (context, never swapped). `ctx.wreck_obstacle` was revised once after the first anchor run: the Ypenburg value closed the wide grass field after one wave.
* **`battlelab report --pairs a:b,c:d`** runs only those swap pairs (both directions). `scripts/reproduce.sh` uses the six pairs the notes discuss by default (`PAIRS=""` runs all): about 47 min instead of about 100 on 4 cores.
* The test invariant "airbridge implies attacker control" now applies only without `risk.land_contested`.

## 0.4.0, earlier entries

* **Two new scenarios: Heraklion and Rethymno 1941**, within-campaign controls for Maleme. They share its Luftwaffe, HQ and airlift values and are sourced from search excerpts only. Their anchors hold in about 98-99% of runs, which is weak evidence because every anchor follows from "the defenders win". What they add is in the swaps. Heraklion with Maleme's factors goes from 0.01 to 0.63 (Rethymno from 0.02 to 0.64), and Maleme's HOLD bundle is the largest contribution under both resolvers (+0.41 and +0.39 under Lanchester). Maleme with Heraklion's defenders alone falls from 0.66 to 0.03. HOLD mixes garrison size with the command-cycle withdrawal, so these swaps cannot separate the two (see results/NOTES.md).
* Parameter expressions in scenario values (`"$hold.strength * (1 - $hold.perimeter_frac)"`: + - * / and parentheses, whitelisted); lint checks references inside them.
* `fires[].from_zone`: a fire acts only while the firing side holds that zone.
* Ypenburg perimeter zone (new HOLD parameters `hold.perimeter_frac`, `hold.perimeter_fire`). Tried and not adopted: sole German control of the field rose only from 0.21 to 0.26, while the joint anchor share fell from 0.54 to 0.46. It is inactive (0) in every scenario.
* **HOLD split into HOLD (garrison) and COMMAND (command-cycle withdrawal).** Swaps are now 7-factor. Result: in the Crete comparison, Maleme's garrison size decides whether it fell (HOLD +0.36 / +0.32 for Heraklion / Rethymno with Maleme's factors), and COMMAND is small (+0.04 / +0.06). Maleme with Heraklion's command behaviour alone stays at 0.65.
* **One-parameter sweeps in the report (section 5b).** Maleme's garrison is swept with and without the command cycle: P(airbridge) is 0.73 at 500 defenders, 0.21 at 1,000, 0.04 at 1,500 and 0.01 at 2,000. Without the command cycle, large garrisons hold less reliably (0.08 at 2,000).
* Hostomel, Maleme and Ypenburg are unchanged run-for-run; the full results were regenerated (20 swap pairs, 7 factors).

## 0.3.0 (2026-09-25)

Model changes. Each is exactly the 0.2.0 model at its default; Hostomel and Maleme were checked run-for-run over 400 runs before Maleme adopted the commitment gate.

* **Surprise shock** (`arrive.shock`, `shock_decay_h`; MASS parameters `mass.shock`, `mass.shock_decay_h`). An air arrival into a zone its side does not hold cuts enemy effectiveness there by shock0·exp(−t/decay). Ypenburg only (0.3–0.7, 1–4 h).
* **No line of retreat** (`Morale.ratio_scale`; MASS parameter `mass.cornered`). This scales the force-ratio term of the morale hazard. Ypenburg's airborne units only (0.2–0.6).
* **Withdrawal move delay** (`Morale.move_delay_h`; HOLD parameter `hold.move_delay_h`). Tried on Maleme and not adopted: it spreads t_control but lowers the joint anchor share from 0.68 to 0.54 (see the parameter note).
* **Attacker commitment gate** (`airlift.commit_lag_h`, `commit_cycle_h`; RISK parameters `risk.commit_lag_h`, `risk.commit_cycle_h`). In shuttle mode the air-landing force is committed only at the HQ's next decision point after the report of control arrives. Maleme only (2–6 h, 6–12 h). First landing p50 moves from H+22.2 (dawn) to H+26.5.
* New metric `attacker_hours_on_field`.

Anchor revisions. Both are recorded in the anchor notes, and the effect of each is reported separately:

* Ypenburg `germans_take_field` (sole control of the one-zone field) becomes `germans_hold_on_field` (German troops on the field for at least 3 h), which is what the source says. Joint share (Lanchester): 0.04 → 0.38 from the anchor alone, 0.54 with both mechanisms. Under the old anchor it is still 0.04.
* Maleme `landings_begin_day2` ([20, 40] h) becomes `landings_begin_day2_afternoon` ([28, 34] h), which is what the source says. Joint share (Lanchester): 0.68 → 0.003 from the anchor alone, 0.20 with the commitment gate.

Report: `results/NOTES.md` holds the hand-written interpretation, with numbers filled in from each run by placeholders. `battlelab report --notes-only` refreshes it; all values are in `results/report_values.csv`.

Results (N = 1000, seed 1; `results/SUMMARY.md`):

| | 0.2.0 | 0.3.0 |
|---|---|---|
| Hostomel joint anchors, Lanchester / CRT | 0.60 / 0.50 | 0.60 / 0.50 |
| Maleme joint anchors, Lanchester / CRT | 0.68 / 0.13 | 0.20 / 0.03 (stricter anchor) |
| Ypenburg joint anchors, Lanchester / CRT | 0.04 / 0.04 | 0.54 / 0.56 (revised anchor) |
| Hostomel with Maleme's factors, Lanchester | 0.33 → 0.74 | 0.33 → 0.74 |
| Maleme with Hostomel's factors, Lanchester | 0.67 → 0.00 | 0.66 → 0.00 |
| Hostomel with Ypenburg's factors, Lanchester | 0.33 → 0.36 | 0.33 → 0.58 |

Changed conclusion: for Maleme with Hostomel's factors, RISK falls from the largest contribution (−0.28) to −0.18, and DENIAL (−0.28) is now the largest. The cause is bundling: the commitment-gate parameters sit in the RISK bundle, so swapping Hostomel's RISK also removes Maleme's commitment delay. Hostomel with Maleme's factors is unchanged (HOLD −0.49, RISK +0.42).

## 0.2.0 (2026-09-24)

Model changes (each reduces exactly to 0.1.0 behaviour at its default; checked run-for-run):

* **Command decision cycles** (`Morale.decision_h`, `comms_loss`, `fog`, `night_moves`). The commander evaluates the fight-or-leave hazard at decision points, possibly without reports (then assuming at least `fog` casualties), and a withdrawal order can wait for darkness. Four new HOLD parameters in every airhead scenario. Maleme uses the NZH account of the 22nd Battalion losing contact with its forward companies and withdrawing overnight.
* **Selectable go/no-go rule** (`mechanics.go_no_go`): the hard `threshold` (default) or `logistic` acceptance (one nerve draw per wave or sortie), both optionally on a risk estimate lagged by `info_lag_h`. New family constants `mech.go_width` and `mech.info_lag_h`.
* **Landing on a contested field** (doctrine `land_contested`, `airlift.contested_risk`): a wave may land into a fight at extra risk, and its troops attack. New RISK parameter `risk.land_contested`, new family constant `mech.contested_risk`.
* **Fix: cross-process nondeterminism.** Combat iterated over a set of side ids, so which side received which Lanchester draw depended on per-process string hashing. 0.1.0 results were statistically, but not exactly, reproducible.

New scenario: **Ypenburg 1940** (third member of the airhead family; thinly sourced, see CLAUDE.md).

### CMO backend

Not yet run in a live CMO build; everything below passes against the mock CMO API.

* `bl_probe.lua`: checks every API assumption in a live build from any scenario, without running the clock.
* `bl_build_hostomel.lua` + `bl_build_db.lua`: builds the whole Hostomel scenario from an empty one; the user only supplies DBIDs.
* Fix: Russian air-assault troops were never put on the ground in CMO (respawned helicopters carry no cargo). They are now scripted RU_VDV_ squads unloaded by each helicopter that reaches the airfield; new metric `vdv_delivered`.
* Fix: `BL.selftest` failed in the documented flow (after the scenario-loaded event had started a batch and emptied the map).
* `cmo-export --start`, a 20-run pilot kit in `cmo/pilot/`, and an end-to-end mock test (build, selftest, replications through `bl_run.lua`).

### Tooling

Schema lint with paths; `battlelab report` (writes results/SUMMARY.md), `resolvers`, `compare-backends`; `--go-rule`, `--set` and `--tag` on every experiment command; one process pool per swap or sweep (3.6x faster on 4 cores); CI with ruff, mypy, pytest and the Lua harness.

Results (all in results/, regenerated with `scripts/reproduce.sh`, N = 1000, seed 1):

| | 0.1.0 | 0.2.0 |
|---|---|---|
| Maleme joint anchors, Lanchester | 0.40 | 0.68 |
| Maleme joint anchors, CRT | 0.09 | 0.13 |
| Hostomel joint anchors, Lanchester / CRT | 0.60 / 0.50 | 0.60 / 0.50 |
| Ypenburg joint anchors, Lanchester / CRT | - | 0.04 / 0.04 |
| Hostomel with Maleme's factors, Lanchester | 0.33 -> 0.75 | 0.33 -> 0.74 |
| Hostomel with Maleme's factors, CRT | 0.36 -> 0.41 | 0.36 -> 0.34 |
| Maleme with Hostomel's factors, Lanchester | 0.69 -> 0.00 | 0.67 -> 0.00 |
| Maleme with Hostomel's factors, CRT | 0.40 -> 0.01 | 0.24 -> 0.01 |

Findings that survive the changes: HOLD and RISK remain the two largest Shapley contributions between Hostomel and Maleme, with the same signs, under both resolvers and under all three go/no-go rules (SUMMARY sections 3 and 4). Hostomel's Shapley values for Maleme's factors move by at most 0.03 when the go/no-go rule changes, so the swap conclusions do not rest on the hard threshold. The zero single-swap of DENIAL is a property of the rule and becomes 0.02 under the logistic rule. Changed: under CRT, the Maleme baseline fell from 0.40 to 0.24. The likely cause (not yet isolated) is that the command cycle holds the NZ battalion on the field until dark, and the CRT's high attacker attrition then wears the paratroops down first.

## 0.1.0 - first draft (2026-09-24)

* Native engine: board-game turn sequence, pluggable mechanics (arrivals and insertion, air situation, fires, combat with Lanchester or CRT resolver, morale, control, runway engineering, airlift, outcome).
* Scenario YAML with per-parameter provenance and lint; `airhead` family with Hostomel 2022 and Maleme 1941.
* Experiments: batches, full-factorial factor swaps, sweeps, manifests. Analysis: Wilson intervals, exact Shapley with bootstrap, anchor checks, ABC rejection calibration, screening.
* CMO harness (Lua): in-session replication loop, Hostomel plugin, self-test; design export and result ingest in Python. Tested against a mock CMO API only.
