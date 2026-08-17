# Level selection model

The active support/resistance map is intentionally **not** a list of nearby strikes.

## Resistance
- Search strikes above spot.
- Use CE OI as the primary wall measure.
- Require upper-distribution OI or a meaningful local OI peak.
- Weight proximity to spot so a relevant nearby wall outranks a distant OI extreme.
- Use CE strength and 5-minute ΔOI as secondary confirmation.

## Support
- Search strikes below spot.
- Use PE OI as the primary wall measure.
- Apply the same high-OI/local-peak/proximity rules.

## Primary and extension levels
- EOS/EOR are the highest-evidence active walls from the filtered candidates.
- EOS-1/EOR+1 are the next stronger OI walls on the corresponding side when available.
- Only when no next strong wall exists does the engine fall back to one strike step.

This prevents ordinary-OI strikes from being presented as actionable support/resistance simply because they are close to spot.


## Latest high-OI wall fix

Active EOS/EOR selection now prioritizes the nearest statistically strong OI wall within 2.25 strike steps of spot before considering farther walls. The selector combines OI percentile, OI relative-to-maximum, local-peak behaviour, distance to spot, strength and ΔOI. Weak intermediate strikes are not promoted merely because they are close.

The chart consumes the same filtered support/resistance arrays as the level cards, so active OI walls such as a strong PE wall immediately below spot are drawn on the chart. Duplicate structural/precision lines are suppressed.
