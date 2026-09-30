# CubePick suite (inspect-robots' built-in world)

5 tasks: inspect-robots' dependency-free `cubepick-reach` benchmark (robocurve/inspect-robots, `src/inspect_robots/mock/cubepick.py`, MIT), ported so the same scenes run under Robo Use. A point end effector starts at (0.1, 0.1) in the unit square and must come within 0.05 of a cube that `numpy.random.RandomState(seed).uniform(0.6, 0.9, 2)` places, exactly as upstream, so task `cubepick-reach-layout-n` is upstream's scene `layout-n`.

- Backend: `src/robouse/backends/cubepick.py`. Generator: `python adapters/cubepick/generate.py`.
- Action `robo act DX DY` (clipped to +-0.1 per step); observation `eef_pos`, `cube_pos`, `distance`; camera `top` (upstream's 32x32 image, upscaled 8x). Success the first time the distance is <= 0.05 (upstream terminates there); budget 80 steps.
- Validation: reference solution (upstream's scripted policy) 5/5 (`runs/cubepick-oracle`), no-op 0/5 (`runs/cubepick-noop`).
