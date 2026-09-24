# Modelling standards

These are the rules that keep this from turning into vibe coding. They are enforced by tooling where possible and by review where not.

## 1. Every number has a provenance

A parameter entry must have either `source:` (a key in the scenario's `sources` block) or `assumption: true`, and may have both (a sourced fact turned into a number by judgement). Add `confidence: low|medium|high` and a `note` quoting or paraphrasing what the source actually says. `battlelab lint` fails on any parameter with neither.

Practical rules:

* Use a range, not a point, when the source gives an approximation ("approximately 200" → 150–220).
* Fixed values are for things that are either well documented (18 Il-76) or modelling constants deliberately held equal across a family (`mech.*`). Constants shared across a family must have identical values in every member, or cross-battle comparisons are meaningless.
* Never tune a parameter to hit an anchor without recording it. If you calibrate, write the calibrated range into the YAML with `source:` pointing to a calibration note and keep the prior in the note.

## 2. Anchors are tests

Anchors state what happened in terms of model metrics (`t_control between [1, 4]`, `airbridge eq false`). Read the anchor report like this:

* A high joint share does **not** validate the model. Many wrong models reproduce a few coarse facts.
* A low share for an individual anchor is a red flag: the model treats history as unusual. Investigate before trusting any counterfactual built on it.
* Prefer several weak, independent anchors (timing, sequence, magnitude) to one strong one. This is pattern-oriented modelling (Grimm et al., 2005): a structure earns trust by reproducing multiple patterns at once.

## 3. Calibration is not validation

`battlelab calibrate` keeps the runs that reproduce all anchors and compares parameter distributions before and after. Two outcomes are informative:

* A parameter whose posterior moves a lot is constrained by the historical record. Consider narrowing its prior, and say so.
* If no parameter moves but the anchor shares are poor, the problem is structural (a missing mechanism), not parametric. Do not respond by widening priors until history fits.

Anchors used for calibration cannot then be cited as independent validation. Hold some out.

## 4. Structural uncertainty is tested, not ignored

At minimum, re-run key results with the alternative combat resolver (`mechanics.combat.resolver: crt`) and with the `mech.*` constants varied (`--set mech.kill_rate=...`). A conclusion that flips when the attrition model changes is a finding about the model, not the battle. The shipped CRT is a generic board-game table: useful for structural comparison, not a calibrated alternative.

## 5. Reading factor swaps and Shapley values

A factor swap asks: "if battle A had battle B's version of this factor, as this model represents it, how would P(outcome) change?" Shapley values split the total change fairly across factors, including interactions. Keep in mind:

* The answer depends on how factors are bundled. Changing the bundles changes the question.
* Bootstrap intervals cover Monte Carlo noise only, not parameter or structural uncertainty.
* A swap can put a factor outside the context where it is meaningful (a 1941 risk tolerance applied to a 2022 air-defence environment). The model will still produce a number. Judge whether the question makes sense before reporting it.
* Context parameters (`ctx.*`) are never swapped; decide deliberately what counts as context.

## 6. Minimum reporting checklist

For any result that leaves the repository:

1. Scenario fingerprints, seeds and run counts (from the manifest).
2. The anchor table for each scenario involved.
3. The share of parameters flagged as assumptions, and which of them the result is most sensitive to (`battlelab screen`).
4. Whether the result survives the alternative resolver.
5. For CMO results: CMO build number (in the CSV), database version, and which plugin mappings were active.

## 7. Engine code

* Mechanics communicate only through world state, `scratch` and `persist`. No hidden globals.
* Each mechanic draws from its own named RNG stream.
* Every new mechanic ships with a test: an invariant (no negative strength, bounded fractions), a known limit (Lanchester expectation), or a scenario-level property.
* Behaviour changes that move results need a note in the changelog and a re-run of the anchor tables.
