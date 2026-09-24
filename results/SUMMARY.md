# Results summary - draft v0.1.0

All numbers come from files in this folder (each with a `.manifest.json`) and can be regenerated with `scripts/reproduce.sh`. Seed 1 throughout. "Lanchester" and "CRT" are the two combat resolvers. Outcome: an airbridge, meaning at least 500 troops air-landed within 48 hours.

These are statements about the model. Most parameters are flagged assumptions (Hostomel 29 of 42, Maleme 34 of 39), and the intervals below cover Monte Carlo noise only.

## 1. Is history a typical outcome in the model?

Share of runs that reproduce each historical fact (n = 2,000 per scenario per resolver; files `anchors_*.csv`).

| Anchor | Lanchester | CRT |
|---|---|---|
| Hostomel: VDV secure the field within 1-4 h | 0.88 | 0.75 |
| Hostomel: Ukraine retakes the field | 0.73 | 0.69 |
| Hostomel: no airbridge | 0.68 | 0.65 |
| Hostomel: runway unusable at the end | 1.00 | 1.00 |
| **Hostomel: all four jointly** | **0.60** | **0.50** |
| Maleme: NZ leave the field between H+4 and H+24 | 0.51 | 0.17 |
| Maleme: first landing on day 2 (H+20 to H+40) | 0.42 | 0.10 |
| Maleme: airbridge established | 0.69 | 0.40 |
| Maleme: NZ counterattack fails | 1.00 | 1.00 |
| **Maleme: all four jointly** | **0.40** | **0.09** |

Hostomel is reproduced well and robustly across resolvers. Maleme is not. The model gives the Germans the field too early and lands transports on day 1 too often, and the Maleme outcome itself depends strongly on the attrition model (airbridge probability 0.69 under Lanchester, 0.40 under CRT).

Rejection calibration against all four Maleme anchors (n = 6,000, acceptance 0.40; `calibrate_maleme_1941.txt`) moves no parameter by more than 0.16 prior standard deviations. No value inside the current priors fixes the timing, so the gap is a missing mechanism. The leading candidate is command decision timing: the 22nd Battalion's withdrawal was an overnight decision taken after losing contact with its forward companies. This is backlog item 1 in `CLAUDE.md`.

## 2. What drives each outcome within its own uncertainty?

First-order variance share of P(airbridge) by parameter (n = 4,000; noise floor about 0.002; `screen_*.csv`).

* **Hostomel:** `denial.t_fires` 0.16, `risk.tolerance` 0.13, `air.att.approach_loss` 0.08, `denial.obstacles0` 0.03, `ctx.wave1_t` 0.03. The outcome turns on the timing of Ukrainian fires relative to the Il-76 wave, and on Russian risk appetite. All three top parameters are low-confidence or flagged assumptions. Better sourcing for when Ukrainian fires on the runway began is the single most valuable research step.
* **Maleme:** `mass.dz_loss` 0.05, `hold.strength` 0.02; everything else is near the noise floor. Most of Maleme's outcome variance is process noise rather than parameter uncertainty: in this model the battle was close to a coin flip.

## 3. Cross-battle factor swaps

A full factorial over six factor bundles (64 configurations per direction, the same seeds throughout), decomposed with Shapley values. Lanchester results use n = 1,000 per configuration; the CRT robustness check uses n = 400. Files: `shapley_*.csv`, `swap_*.csv`, `shapley.png`, `shapley_crt.png`.

**Hostomel given Maleme's factors.** P(airbridge) moves from 0.33 to 0.75 under Lanchester, and from 0.36 to 0.41 under CRT.

| Factor | Shapley (Lanchester) | Shapley (CRT) | Single swap alone (Lanchester) |
|---|---|---|---|
| HOLD (defenders) | -0.44 | -0.52 | 0.02 |
| RISK (landing risk tolerance) | +0.43 | +0.36 | 0.90 |
| MASS (assault force) | +0.20 | +0.14 | 0.46 |
| AIR | +0.19 | +0.18 | 0.63 |
| RESPONSE (counterattack) | +0.05 | +0.02 | 0.35 |
| DENIAL (fires, obstacles, demolition) | -0.01 | -0.13 | 0.00 |

**Maleme given Hostomel's factors.** P(airbridge) moves from 0.69 to 0.00 under Lanchester, and from 0.40 to 0.01 under CRT.

| Factor | Shapley (Lanchester) | Shapley (CRT) | Single swap alone (Lanchester) |
|---|---|---|---|
| RISK | -0.30 | -0.27 | 0.21 |
| HOLD | +0.24 | +0.32 | 1.00 |
| MASS | -0.19 | -0.13 | 0.09 |
| DENIAL | -0.19 | -0.09 | 0.18 |
| AIR | -0.13 | -0.13 | 0.42 |
| RESPONSE | -0.12 | -0.09 | 0.47 |

Robust across resolvers: RISK and HOLD are the two largest contributions in both directions, with the same signs. Giving the Russians the Germans' 1941 risk tolerance alone lifts Hostomel from 0.33 to 0.90. Giving the Germans the Russians' caution alone drops Maleme from 0.69 to 0.21. Hostomel's weak garrison was a gift; Maleme's defenders alone would have stopped the 2022 assault (0.02).

Not robust: the size of the endpoint effects, and the DENIAL contribution (-0.01 vs -0.13).

Artefact to keep in mind: the single swap of Maleme's DENIAL into Hostomel gives exactly 0.00. The landing decision is a hard threshold, and Maleme-style fire from H-hour always exceeds Russian tolerance. That is a property of the rule (backlog item 2), not a historical finding.

## 4. Counterfactual surface for Hostomel

P(airbridge) over Russian risk tolerance (0 to 0.4) and the start of Ukrainian fires (H+1 to H+12), n = 300 per cell (`sweep_hostomel_2022.png`). Inside the historical box (tolerance 0.03-0.08, fires from H+4 to H+7) the probability runs from about 0.01 to 0.45. At tolerance 0.10 with fires from H+6 it is 0.84. The surface has a cliff: once fires begin after the first wave's landing window, even modest risk appetite produces an airbridge. If fires start earlier, only tolerances of roughly 0.25 or more give reasonable odds.

## 5. CMO backend

The harness passes its offline tests against a mock of the CMO Lua API in file-output mode, in KeyStore-fallback mode, and with Python-generated designs; `cmo-ingest` reads its output back into the same analysis. It has not yet run in a live CMO build. See `cmo/SETUP.md`.
