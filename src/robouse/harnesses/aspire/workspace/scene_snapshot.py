# Scene snapshot: Robo Use's stand-in for ASPIRE's scripts/scene_snapshot.py, whose tools (get_task_context,
# segment_text, ...) this task does not have. Run it once, on the first development seed:
#
#   cap-harness run --benchmark <benchmark> --suite <suite> --task-id <id> --seed <FIRST_DEV_SEED> \
#     --program docs/scene_snapshot.py --output-root "$TASK_DIR/debug/explore" --flat-run-dir --no-videos
#
# It moves nothing. It records the task's step budget and API functions and the robot's state in result
# (source/program-result.json), and a camera image of the untouched scene (media/keyframes/). Copy it into
# $TASK_DIR/code/ as probe_<slug>.py to probe more, for example the poses the task's API returns for each object
# the task text names.

info = robo.info()
seen = robo.observe(image=True)
result = {
    "task": info.get("task"),
    "backend": info.get("backend"),
    "api_functions": [name for name in info.get("skills", []) if name != "capx_continue"],
    "max_steps": info.get("max_steps"),
    "steps_used": info.get("steps_used"),
    "action": info.get("action"),
    "robot_state": seen.get("state"),
    "image": seen.get("image_path"),
}
