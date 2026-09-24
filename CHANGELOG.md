# Changelog

## 0.1.0 - first draft (2026-09-24)

* Native engine: board-game turn sequence, pluggable mechanics (arrivals and insertion, air situation, fires, combat with Lanchester or CRT resolver, morale, control, runway engineering, airlift, outcome).
* Scenario YAML with per-parameter provenance and lint; `airhead` family with Hostomel 2022 and Maleme 1941.
* Experiments: batches, full-factorial factor swaps, sweeps, manifests. Analysis: Wilson intervals, exact Shapley with bootstrap, anchor checks, ABC rejection calibration, screening.
* CMO harness (Lua): in-session replication loop, Hostomel plugin, self-test; design export and result ingest in Python. Tested against a mock CMO API only.
