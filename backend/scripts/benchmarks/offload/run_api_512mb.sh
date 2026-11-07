#!/bin/sh
# The API stand-in inside a 512 MiB memory cgroup (cgroup v1, root), restarted whenever it dies, like Render.
# Needs: CG (cgroup dir with memory.limit_in_bytes=536870912), PORT, LOG; SIM_* settings as in api_sim.py.
cd "$(dirname "$0")"
while true; do
  echo "$(date +%s.%N) start" >> "$LOG"
  sh -c "echo \$\$ > $CG/cgroup.procs; exec uvicorn api_sim:app --host 127.0.0.1 --port $PORT --log-level warning"
  echo "$(date +%s.%N) exit $?" >> "$LOG"
  sleep 1
done
