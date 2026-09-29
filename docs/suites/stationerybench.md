# StationeryBench suite (real robot, bimanual)

5 tasks from StationeryBench (robocurve/stationerybench @ 43d5dd3, MIT; listed in the WorldEvals catalog): uncap a marker, take an eraser out of a box, pull the middle sticky pad from a stack, pour paper clips into a lifted bowl, hand a ruler from arm to arm. Each has one fixed setup, the verbatim instruction and a 0-4 stage rubric; upstream runs 20 repetitions per task and model on I2RT YAM arms and scores success at stage 4.

- Here the tasks run on two SO-101 follower arms (`real.robot: so101-bimanual`, LeRobot `bi_so_follower`), with the operator giving the rubric stage after `robo done` (`real.rubric`); stage / 4 is the progress metric. Generator: `python adapters/stationerybench/generate.py`. See [Real robots](../real-robots.md).
- Default driver: the hardware-in-the-loop mock (fixture `so101-bimanual-sort`, recorded SO-101 poses and stills). The mock models no contact, so its stand-in operator credits stage 0: on the mock these tasks check the pipeline (gates, safety, rubric verdicts, recording, metrics), not the skill. Run the published protocol on a rig: `robouse run-many --tasks tasks/stationerybench --harness ... --rig rig.yaml --epochs 20`.

| Check (mock) | Result | Folder |
|---|---|---|
| pipeline run (arms home, grippers open, done), stand-in operator | 0/5, progress 0 | `runs/stationery-oracle-mock` |
| same, operator script `verdict=4` | 5/5, progress 1.0 | `runs/stationery-oracle-scripted4` |
| same, operator script `verdict=2` | 0/1, progress 0.5 | `runs/stationery-oracle-scripted2` |

Not tested: the tasks on real arms (no rig was connected). Differences from upstream: SO-101 arms (5 joints + gripper each) instead of YAM arms (6 + gripper); no upstream reference photos or demonstration videos are bundled (see the upstream task reference).
