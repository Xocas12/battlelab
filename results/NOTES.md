# Notes

Hand-written interpretation. Every number below is a placeholder filled in from this run's tables (`battlelab report --notes-only` refreshes them), so the text cannot cite a number the tables no longer contain. These notes are statements about the model; most parameters are flagged assumptions.

**How far to trust each scenario.**

* **Hostomel.** It reproduces its history well: all four facts hold jointly in {{anchor.hostomel_2022.lanchester.joint|pct}} of runs under Lanchester and {{anchor.hostomel_2022.crt.joint|pct}} under the CRT.
* **Maleme.** It looks worse than in 0.2.0 ({{anchor.maleme_1941.lanchester.joint|pct}} joint under Lanchester) because its first-landing anchor was tightened from "day 2" to "the afternoon of day 2", not because the model got worse. The commitment gate moved the first landings toward the afternoon, but most runs still land in the morning.
* **Ypenburg.** It reaches {{anchor.ypenburg_1940.lanchester.joint|pct}}. That is mostly because its control anchor was reread as "German troops on the field for at least 3 hours" rather than sole control, and partly because of the airborne ammunition limit and the second counterattack (#13). Its parameters are thinly sourced (issue #4).

**What the factor swaps say.**

* **Hostomel with Maleme's factors.** Swapping all seven bundles raises P(airbridge) from {{swap.hostomel_2022__maleme_1941.lanchester.base}} to {{swap.hostomel_2022__maleme_1941.lanchester.full}}. The largest contributions are Maleme's defenders (HOLD, {{shapley.hostomel_2022__maleme_1941.lanchester.HOLD|signed}}) and German risk tolerance (RISK, {{shapley.hostomel_2022__maleme_1941.lanchester.RISK|signed}}), with the same signs under the CRT. RISK alone lifts Hostomel to {{single.hostomel_2022__maleme_1941.lanchester.RISK}}. Maleme's defenders alone would have stopped the 2022 assault ({{single.hostomel_2022__maleme_1941.lanchester.HOLD}}).
* **Maleme with Hostomel's factors.** The airbridge disappears ({{swap.maleme_1941__hostomel_2022.lanchester.base}} to {{swap.maleme_1941__hostomel_2022.lanchester.full}}). DENIAL is now the largest single contribution ({{shapley.maleme_1941__hostomel_2022.lanchester.DENIAL|signed}}); RISK is {{shapley.maleme_1941__hostomel_2022.lanchester.RISK|signed}}.
  * RISK used to be largest, and it shrank because of the bundling. The new commitment-gate parameters sit in the RISK bundle, so swapping in Hostomel's RISK also removes Maleme's commitment delay, which offsets part of the lower risk tolerance. This is the "the answer depends on the bundles" caveat of MODELING_STANDARDS §5, not a new finding about 1941. Swapped alone, Hostomel's RISK drops Maleme to {{single.maleme_1941__hostomel_2022.lanchester.RISK}}.
* **Swaps involving Ypenburg.** These should be read as provisional until issue #4 is done. Ypenburg's MASS bundle now carries the surprise shock and no-retreat morale, which is why Hostomel with Ypenburg's factors rises to {{swap.hostomel_2022__ypenburg_1940.lanchester.full}}.

**The Crete controls: what made Maleme different?** Heraklion and Rethymno share Maleme's Luftwaffe, HQ and airlift values, so a swap between them isolates what differed on the ground.

* **Maleme's garrison decides it, not its withdrawal.** The defenders' parameters are now two bundles: HOLD (garrison size, quality, entrenchment) and COMMAND (decision cycle, lost contact, fog, night moves).
  * Heraklion with all of Maleme's factors goes from {{swap.heraklion_1941__maleme_1941.lanchester.base}} to {{swap.heraklion_1941__maleme_1941.lanchester.full}}, and Rethymno from {{swap.rethymno_1941__maleme_1941.lanchester.base}} to {{swap.rethymno_1941__maleme_1941.lanchester.full}}.
  * In both, HOLD is the largest contribution ({{shapley.heraklion_1941__maleme_1941.lanchester.HOLD|signed}} and {{shapley.rethymno_1941__maleme_1941.lanchester.HOLD|signed}}; under the CRT {{shapley.heraklion_1941__maleme_1941.crt.HOLD|signed}} and {{shapley.rethymno_1941__maleme_1941.crt.HOLD|signed}}). COMMAND is small ({{shapley.heraklion_1941__maleme_1941.lanchester.COMMAND|signed}} and {{shapley.rethymno_1941__maleme_1941.lanchester.COMMAND|signed}}).
* **The reverse holds.** Maleme with Heraklion's garrison alone falls from {{swap.maleme_1941__heraklion_1941.lanchester.base}} to {{single.maleme_1941__heraklion_1941.lanchester.HOLD}}. With Heraklion's command behaviour alone (no command cycle) it stays at {{single.maleme_1941__heraklion_1941.lanchester.COMMAND}}.
* **How big a garrison would have held Maleme** (section 5b):
  * P(airbridge) falls from {{linesweep.maleme_garrison.500}} with 500 defenders at the field to {{linesweep.maleme_garrison.1000}} with 1,000, {{linesweep.maleme_garrison.1500}} with 1,500 and {{linesweep.maleme_garrison.2000}} with 2,000.
  * Without the command cycle the curve is almost the same at Maleme's own size ({{linesweep.maleme_garrison_no_command.650}} against {{linesweep.maleme_garrison.650}} at 650). It is flatter for big garrisons ({{linesweep.maleme_garrison_no_command.2000}} at 2,000), because turn-by-turn morale lets even a large garrison drift away, while a commander who judges the situation holds.
  * So in this model, the lost contact and night withdrawal explain *when* Maleme fell (the timing anchors), while the size of the force at the field explains *whether*.
* **Sanity check.** RISK contributes exactly {{shapley.heraklion_1941__maleme_1941.lanchester.RISK|signed}}, because the three share the same HQ values. Any other number would mean the swap machinery leaks.
* **Caveats.**
  * The finding rests on judged garrison sizes: 500-650 at Maleme, and 1,500-3,000 of Heraklion's 8,024 able to fight at the airfield. With a Heraklion garrison below about 1,000, the comparison would look different; see the sweep.
  * It is also a statement about this model's attrition and morale, not a historical verdict. The common reading stresses the 22nd Battalion's withdrawal, and the model does reproduce that withdrawal; it just does not need it to lose Maleme.
* **Weak anchors.** The Heraklion and Rethymno anchors hold in about 98-99% of runs, which only says the model lets strong, alert defenders win. Their sourcing is search excerpts only.

**Valkenburg: the ground, not the fight.** Valkenburg is the same operation as Ypenburg on an unfinished airfield that could not carry loaded Ju 52s.

* **The soft-ground mechanic works.** Many transports get stranded ({{anchor.valkenburg_1940.lanchester.many_transports_stranded|pct}} of runs strand at least 20), and the Germans take the field ({{anchor.valkenburg_1940.lanchester.germans_take_field|pct}}).
* **The recapture needs two things.** The Dutch retake the field in {{anchor.valkenburg_1940.lanchester.dutch_retake_field|pct}} of runs, and all four facts hold together in {{anchor.valkenburg_1940.lanchester.joint|pct}} (issue #13). It took two mechanisms:
  * The airborne troops run out of ammunition after 6-14 h of fighting (`mass.ammo_out_h`). This alone lifts the recapture from 7% to 29%.
  * A second, later Dutch counterattack (`response.t_ca2`, `response.strength2`). One counterattack cannot both let the Germans take the field and take it back the same day; two successive efforts, as in the history, can.
  * Both are assumptions set before their anchor runs. A third idea, disorganised troops from bogged aircraft, was tried and not adopted (it made the Germans weaker without making the recapture likelier).
* **The factor swap is nearly silent.** Ypenburg and Valkenburg share almost every factor value, so Valkenburg with Ypenburg's factors only moves from {{swap.valkenburg_1940__ypenburg_1940.lanchester.base}} to {{swap.valkenburg_1940__ypenburg_1940.lanchester.full}} (all of it HOLD, {{shapley.valkenburg_1940__ypenburg_1940.lanchester.HOLD|signed}}). What differed was the airfield itself (soft ground, a wide grass surface, a fourth wave), and that is context (`ctx.*`), which swaps never exchange by design (MODELING_STANDARDS §5). Answering "why did Valkenburg differ from Ypenburg" needs a context comparison, not a factor swap.
* **Sources.** Search excerpts only (Stichting Historie Vliegveld Valkenburg, Forgotten Airfields). One prior (`ctx.wreck_obstacle`) was revised after the first anchor run, and its note says so.

**Structural checks.** The Hostomel–Maleme swap conclusions do not depend on the go/no-go rule: see section 4, where threshold, logistic and lagged rules give Shapley values within a few hundredths of each other. The CRT remains illustrative (section 6); magnitudes under it should not be read.
