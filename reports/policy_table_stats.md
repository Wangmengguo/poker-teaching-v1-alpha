# Policy Table Stats

- preflop: nodes=24
  - sample: preflop|single_raised|caller|ip|texture=na|spr=na|facing=na|hand=junk
  - sample: preflop|single_raised|caller|ip|texture=na|spr=na|facing=na|hand=medium_pair
  - sample: preflop|single_raised|caller|ip|texture=na|spr=na|facing=na|hand=premium_pair
  - meta.solver_backend=heuristic
  - meta.seed=42
  - meta.generated_at=2025-10-08T10:58:30.897998+00:00

- postflop: nodes=8832
  - sample: flop|limped|na|ip|texture=dry|spr=na|facing=half|hand=air
  - sample: flop|limped|na|ip|texture=dry|spr=na|facing=half|hand=middle_pair_or_third_minus
  - sample: flop|limped|na|ip|texture=dry|spr=na|facing=half|hand=overcards_no_bdfd
  - meta.solver_backend=heuristic
  - meta.seed=42
  - meta.generated_at=2025-10-08T10:58:30.897998+00:00
