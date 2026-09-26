# Notes

Hand-written interpretation. Every number below is a placeholder filled in from this run's tables (`battlelab report --notes-only` refreshes them), so the text cannot cite a number the tables no longer contain. These notes are statements about the model; most parameters are flagged assumptions.

**How far to trust each scenario.**

* **Hostomel.** It reproduces its history well: all four facts hold jointly in {{anchor.hostomel_2022.lanchester.joint|pct}} of runs under Lanchester and {{anchor.hostomel_2022.crt.joint|pct}} under the CRT.
* **Maleme.** It looks worse than in 0.2.0 ({{anchor.maleme_1941.lanchester.joint|pct}} joint under Lanchester) because its first-landing anchor was tightened from "day 2" to "the afternoon of day 2", not because the model got worse. The commitment gate moved the first landings toward the afternoon, but most runs still land in the morning.
* **Ypenburg.** It reaches {{anchor.ypenburg_1940.lanchester.joint|pct}}, but mostly because its control anchor was reread as "German troops on the field for at least 3 hours" rather than sole control. Its parameters are thinly sourced (issue #4).

**What the factor swaps say.**

* **Hostomel with Maleme's factors.** Swapping all six bundles raises P(airbridge) from {{swap.hostomel_2022__maleme_1941.lanchester.base}} to {{swap.hostomel_2022__maleme_1941.lanchester.full}}. The largest contributions are Maleme's defenders (HOLD, {{shapley.hostomel_2022__maleme_1941.lanchester.HOLD|signed}}) and German risk tolerance (RISK, {{shapley.hostomel_2022__maleme_1941.lanchester.RISK|signed}}), with the same signs under the CRT. RISK alone lifts Hostomel to {{single.hostomel_2022__maleme_1941.lanchester.RISK}}. Maleme's defenders alone would have stopped the 2022 assault ({{single.hostomel_2022__maleme_1941.lanchester.HOLD}}).
* **Maleme with Hostomel's factors.** The airbridge disappears ({{swap.maleme_1941__hostomel_2022.lanchester.base}} to {{swap.maleme_1941__hostomel_2022.lanchester.full}}). DENIAL is now the largest single contribution ({{shapley.maleme_1941__hostomel_2022.lanchester.DENIAL|signed}}); RISK is {{shapley.maleme_1941__hostomel_2022.lanchester.RISK|signed}}.
  * RISK used to be largest, and it shrank because of the bundling. The new commitment-gate parameters sit in the RISK bundle, so swapping in Hostomel's RISK also removes Maleme's commitment delay, which offsets part of the lower risk tolerance. This is the "the answer depends on the bundles" caveat of MODELING_STANDARDS §5, not a new finding about 1941. Swapped alone, Hostomel's RISK drops Maleme to {{single.maleme_1941__hostomel_2022.lanchester.RISK}}.
* **Swaps involving Ypenburg.** These should be read as provisional until issue #4 is done. Ypenburg's MASS bundle now carries the surprise shock and no-retreat morale, which is why Hostomel with Ypenburg's factors rises to {{swap.hostomel_2022__ypenburg_1940.lanchester.full}}.

**The Crete controls: what made Maleme different?** Heraklion and Rethymno share Maleme's Luftwaffe, HQ and airlift values, so a swap between them isolates what differed on the ground.

* **Maleme's defenders decide it.** Heraklion with all of Maleme's factors goes from {{swap.heraklion_1941__maleme_1941.lanchester.base}} to {{swap.heraklion_1941__maleme_1941.lanchester.full}}, and Rethymno from {{swap.rethymno_1941__maleme_1941.lanchester.base}} to {{swap.rethymno_1941__maleme_1941.lanchester.full}}. In both, the largest contribution is Maleme's HOLD bundle ({{shapley.heraklion_1941__maleme_1941.lanchester.HOLD|signed}} and {{shapley.rethymno_1941__maleme_1941.lanchester.HOLD|signed}}), under both resolvers.
* **The reverse holds.** Maleme with Heraklion's defenders alone falls from {{swap.maleme_1941__heraklion_1941.lanchester.base}} to {{single.maleme_1941__heraklion_1941.lanchester.HOLD}}.
* **Sanity check.** RISK contributes exactly {{shapley.heraklion_1941__maleme_1941.lanchester.RISK|signed}}, because the three share the same HQ values. Any other number would mean the swap machinery leaks.
* **Caveat.** Maleme's HOLD bundle mixes garrison size and quality with the command-cycle withdrawal (lost contact, fog, withdrawing at night), so this swap cannot tell "fewer defenders" from "the defenders pulled out". Splitting HOLD into two bundles would; the finding matches the usual reading of Maleme, but that is not independent evidence, because the withdrawal was modelled to reproduce it.
* **Weak anchors.** The Heraklion and Rethymno anchors hold in about 98-99% of runs, which only says the model lets strong, alert defenders win. Their sourcing is search excerpts only.

**Structural checks.** The Hostomel–Maleme swap conclusions do not depend on the go/no-go rule: see section 4, where threshold, logistic and lagged rules give Shapley values within a few hundredths of each other. The CRT remains illustrative (section 6); magnitudes under it should not be read.
