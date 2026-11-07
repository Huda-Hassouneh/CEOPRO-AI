"""Samples the processor's whole process tree (server + task children): RSS and CPU, every 0.25 s."""
import json, sys, time, psutil
pid, out, duration = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
root = psutil.Process(pid); samples = []; t0 = time.time(); cpu_prev = {}
while time.time() - t0 < duration:
    try:
        procs = [root] + root.children(recursive=True)
        rss = 0; cpu = 0.0
        for p in procs:
            try:
                rss += p.memory_info().rss
                t = p.cpu_times(); total = t.user + t.system
                cpu += total - cpu_prev.get(p.pid, total); cpu_prev[p.pid] = total
            except psutil.Error:
                pass
        samples.append((round(time.time() - t0, 2), round(rss / 2**20, 1), len(procs), round(cpu / 0.25 * 100)))
    except psutil.Error:
        samples.append((round(time.time() - t0, 2), None, 0, 0))
    time.sleep(0.25)
json.dump(samples, open(out, "w"))
print(json.dumps({"peak_tree_rss_mb": max((s[1] or 0) for s in samples), "idle_rss_mb": samples[0][1],
                  "peak_processes": max(s[2] for s in samples), "peak_cpu_pct": max(s[3] for s in samples)}))
