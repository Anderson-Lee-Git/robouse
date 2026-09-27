#!/bin/sh
# Entry point of the trusted `simulator` service.
#
# Runs one robouse episode server for the task mounted at /task, with the socket in the shared /rpc
# volume (the agent container mounts it read-only) and the episode record in /episode (simulator only).
# After the episode server exits, the container stays up so BenchFlow can run the verifier in it.
# Extra arguments are passed to `robouse serve` (for example --seed N or --max-wall-s S).
umask 000                     # the agent runs as another user; it must be able to connect to the socket
mkdir -p /rpc/ws /episode
rm -f /episode/serve.exit
python -m robouse.cli serve --task /task --run-dir /episode --socket /rpc/episode.sock \
    --workspace /rpc/ws "$@" > /episode/serve.log 2>&1
echo "$?" > /episode/serve.exit
exec sleep infinity
