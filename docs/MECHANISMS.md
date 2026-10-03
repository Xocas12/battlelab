# Mechanisms

What the native engine models, one mechanism at a time: what it does, the parameters that drive it, its default, and which scenarios switch it on. Every mechanism added after 0.1.0 reduces exactly to the earlier model at its default; that was checked run-for-run when it was added. Parameter values, sources and notes for every scenario are in [PARAMETERS.md](PARAMETERS.md) and the scenario files. The turn sequence and the architecture are in [ARCHITECTURE.md](ARCHITECTURE.md).

"Bundle" is the factor bundle the parameter is swapped in (AIR, MASS, HOLD, COMMAND, RESPONSE, DENIAL, RISK). `ctx.*` parameters are context and are never swapped; `mech.*` and `doctrine.*` are family constants, identical in every scenario.

## Insertion (phase SCHEDULE)

| Mechanism | What it does | Parameters | Used by |
|---|---|---|---|
| Air arrival | Parachute, glider or helicopter units arrive at a set time. Each aircraft is lost with probability `ingress_loss` (binomial), and a drop-zone fraction of the troops is lost. | `air.att.ingress_loss` (AIR), `mass.aircraft`, `mass.capacity`, `mass.dz_loss` (MASS) | all |
| Airborne reserve | A second drop, made only if own troops still hold or contest the zone. | `mass.reserve_*`, `mass.t_reserve` (MASS) | Maleme |
| Surprise shock (0.3.0) | An air arrival into a zone its side does not hold cuts the enemy's effectiveness there by shock0·exp(−Δt/decay). | `mass.shock`, `mass.shock_decay_h` (MASS); default 0 | Ypenburg, Valkenburg |

## Air and fires (phases AIR, FIRES)

| Mechanism | What it does | Parameters | Used by |
|---|---|---|---|
| Air situation | Close air support multiplies own effectiveness; suppression removes a share of the enemy's fire effect; interdiction removes a share of the enemy's attacking strength. All are scaled at night if air power is day-only. | `air.att.*` (AIR), `ctx.night_limited_air` | all |
| Fires | Indirect fire on a zone. It supports own units fighting there, raises the landing risk for enemy aircraft, and craters a runway the firing side does not hold. | `denial.t_fires`, `denial.fire_intensity`, `denial.crater_rate` (DENIAL) | all |
| Zone-gated fire (0.4.0) | A fire acts only while the firing side holds `from_zone`. | `fires[].from_zone`; `hold.perimeter_fire` (HOLD), default 0 | Ypenburg perimeter (tried, inactive) |

## Combat and morale (phases COMBAT, MORALE)

| Mechanism | What it does | Parameters | Used by |
|---|---|---|---|
| Resolver | Losses per side in each contested zone. Stochastic Lanchester square law (default), or an illustrative board-game table (CRT) for structural checks; `battlelab resolvers` compares the two. | `mech.kill_rate`; `mechanics.combat.resolver` | all |
| Effective strength | strength × quality × entrenchment (defending) × (1 − enemy interdiction) (attacking) × close air support × (1 + weight × own fire) × (1 − enemy shock). | `hold.quality`, `hold.dug_in` (HOLD), `doctrine.hasty_defense` | all |
| Morale hazard | Per-hour hazard of leaving the fight: base + ratio term × ratio_scale × (enemy/own − 1) + casualty term × losses + ammunition term once ammunition runs out. There are also immediate exits: collapse, outmatched (`withdraw_ratio`), counterattack commitment expired, and a forced CRT retreat. | `hold.base_hazard`, `hold.ammo_out_h` (HOLD); `response.commit_h`, `response.withdraw_ratio` (RESPONSE); `mech.ratio_coeff`, `mech.casualty_coeff`, `mech.ammo_hazard` | all |
| Command decision cycle (0.2.0) | The fight-or-leave hazard is judged by the commander every `decision_h` hours. With probability `comms_loss` there are no reports, and the commander then assumes at least `fog` casualties. With `night_moves` a withdrawal order waits for darkness, and `move_delay_h` delays it further (exponential). | `hold.decision_h`, `hold.comms_loss`, `hold.fog`, `hold.night_moves`, `hold.move_delay_h` (COMMAND); default 0 | Maleme (move delay tried, inactive) |
| No line of retreat (0.3.0) | Scales the force-ratio term for encircled airborne troops (below 1: they hold at worse odds). | `mass.cornered` (MASS); default 1 | Ypenburg, Valkenburg |
| Airborne ammunition limit (0.4.0) | Parachuted and air-landed units run dry after this many hours of fighting, which switches on the ammunition hazard. | `mass.ammo_out_h` (MASS); default 1000 h (not binding) | Ypenburg (Valkenburg set it to 1000 h in 0.5.0: the pocket held out to 14 May) |

## Control and engineering (phases CONTROL, ENGINEERING)

| Mechanism | What it does | Parameters | Used by |
|---|---|---|---|
| Zone control | A zone belongs to the only side with active units in it; it is contested if both are there; an empty zone keeps its last controller. On capture, the side's units there switch to defence with the hasty-defence bonus. | `doctrine.hasty_defense` | all |
| Runway | Usable fraction = (1 − obstacles)(1 − craters). Whichever side holds the field alone applies its doctrine every turn: the attacker clears obstacles (`clear_rate`), and the defender demolishes (`demolish_rate`) — in practice once the landing force has broken or after a retake, since the field is contested from the first landing. | `denial.obstacles0`, `denial.demolish_rate` (DENIAL), `doctrine.clear_rate` | all |
| Redeployment (0.5.0) | Once, `after_control_h` hours after a side first holds `from_zone`, a `fraction` of each listed unit's strength there leaves for `to_zone` and joins `to_unit` (defending). The moved troops no longer count on the field. | `redeploy:` section; `ctx.redeploy_delay_h`, `ctx.redeploy_frac`; default: no section | Valkenburg (Germans moving into the village) |
| Perimeter zone (0.4.0) | A second zone for defenders at the edge of the field, split from the garrison by an expression (`"$hold.strength * (1 - $hold.perimeter_frac)"`). | `hold.perimeter_frac` (HOLD); default 0 | Ypenburg (tried, inactive) |

## Air-landing (phase AIRLIFT)

| Mechanism | What it does | Parameters | Used by |
|---|---|---|---|
| Waves or shuttle | Transport waves at set times (loitering, then aborting), or a shuttle that starts after control of the field. Landed troops join one unit at an organisation fraction. Lost aircraft leave wrecks on the runway. | `ctx.aircraft`, `ctx.troops_per_aircraft`, `ctx.wave*_t`, `ctx.interval_h`, `ctx.exploit_delay`, `ctx.wreck_obstacle` | all |
| Wave sizes (0.5.0) | `airlift.wave_aircraft` gives each wave its own number of aircraft instead of `ctx.aircraft` for all. | `ctx.wave*_n`; default: every wave uses `ctx.aircraft` | Valkenburg |
| Go/no-go rule (0.2.0) | A wave lands if the side holds the field, the runway is usable enough, and the expected loss per aircraft is acceptable. The rule is a hard threshold (default), or logistic, with one nerve draw per wave. The risk estimate can lag reality by `info_lag_h`. | `risk.tolerance` (RISK), `mech.go_width`, `mech.info_lag_h`; `mechanics.go_no_go.rule` | all |
| Landing on a contested field (0.2.0) | With this doctrine, a wave may land while the field is contested, at an extra per-aircraft loss, and its troops attack off the aircraft. | `risk.land_contested` (RISK), `mech.contested_risk`; default 0 | Ypenburg, Valkenburg |
| Commitment gate (0.3.0) | In shuttle mode, the first sortie waits until the HQ has heard of control (a reporting lag) and reached its next decision point. | `risk.commit_lag_h`, `risk.commit_cycle_h` (RISK); default 0 | Maleme, Heraklion, Rethymno (lag only since 0.6.0) |
| Daylight confirmation (0.6.0) | Control gained at night (20:00-06:00) reaches the HQ only after the next dawn, then the reporting lag applies. | `risk.commit_daylight` (RISK); default 0 | Maleme, Heraklion, Rethymno |
| Soft ground (0.4.0) | Each landed aircraft may sink into the ground: its troops get off, the aircraft stays on the strip as an obstacle, and it is counted in `transports_stranded`. | `ctx.bog_risk`; default 0 | Valkenburg |

## Response (phase SCHEDULE)

| Mechanism | What it does | Parameters | Used by |
|---|---|---|---|
| Counterattack | A defender force arrives at a set time and attacks, and gives up after `commit_h`. | `response.t_ca`, `response.strength`, `response.commit_h`, `response.withdraw_ratio` (RESPONSE) | all |
| Second counterattack (0.4.0) | A later, separate counterattack force. | `response.t_ca2`, `response.strength2` (RESPONSE); default strength 0 | Ypenburg, Valkenburg, Heraklion (0.5.0) |
| Ground relief | An attacker column arriving at a set time (context). | `ctx.t_relief`, `ctx.relief_strength` | Hostomel |

## Metrics (phase RECORD)

`landed`, `airbridge` (≥ 500 troops landed), `t_airbridge`, `t_first_landing`, `transports_lost`, `transports_stranded`, `t_control`, `attacker_ever_controls`, `attacker_hours_on_field`, `attacker_lost_control`, `attacker_holds_end`, `defender_retakes`, `runway_end`, `losses_attacker`, `losses_defender`. Anchors are written in these metrics; `Scenario.lint` rejects any other name.

## Tried and not adopted

These are kept in the code at an inactive default, each with a parameter note recording the experiment:

* **Withdrawal move delay at Maleme.** It spreads the withdrawal time, but the joint anchor share fell from 0.68 to 0.54.
* **Ypenburg perimeter zone.** Sole German control rose only from 0.21 to 0.26, and the joint anchor share fell from 0.54 to 0.46.

Reverted, with the experiment recorded on the issue:

* **Lower organisation for troops from bogged aircraft** (#13). The joint anchor share did not change.
