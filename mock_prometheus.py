
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import time
import urllib.parse

METRICS = {
    "DCGM_FI_DEV_GPU_TEMP",
    "DCGM_FI_DEV_POWER_USAGE",
    "DCGM_FI_DEV_GPU_UTIL",
    "DCGM_FI_DEV_MEM_COPY_UTIL",
    "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS",
}


def metric_value(metric: str, node_idx: int, gpu_idx: int, t: float) -> float:
    phase = (t / 60.0) + node_idx * 0.7 + gpu_idx * 0.4
    hot_zone = 1 if node_idx in [4, 5, 6, 7] else 0
    spike = 1 if (int(t / 60) % 80) > 35 else 0
    if metric == "DCGM_FI_DEV_GPU_TEMP":
        return 56 + 6 * math.sin(phase / 5) + hot_zone * 8 + spike * hot_zone * 18 + gpu_idx * 0.8
    if metric == "DCGM_FI_DEV_POWER_USAGE":
        return 180 + 25 * math.sin(phase / 3) + hot_zone * 30 + spike * hot_zone * 80
    if metric == "DCGM_FI_DEV_GPU_UTIL":
        return max(0, min(100, 45 + 20 * math.sin(phase / 4) + spike * 40))
    if metric == "DCGM_FI_DEV_MEM_COPY_UTIL":
        return max(0, min(100, 35 + 18 * math.sin(phase / 6) + spike * 25))
    if metric == "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS":
        return 1 if metric_value("DCGM_FI_DEV_GPU_TEMP", node_idx, gpu_idx, t) > 90 else 0
    return 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/v1/query":
            self._send({"status": "success", "data": {"resultType": "vector", "result": []}})
            return
        if parsed.path != "/api/v1/query_range":
            self.send_response(404)
            self.end_headers()
            return
        metric = qs.get("query", [""])[0]
        start = float(qs.get("start", [time.time() - 3600])[0])
        end = float(qs.get("end", [time.time()])[0])
        step_raw = qs.get("step", ["60s"])[0]
        step = int(float(step_raw[:-1])) if step_raw.endswith("s") else int(float(step_raw))
        result = []
        if metric in METRICS:
            for node_idx in range(12):
                for gpu_idx in range(4):
                    values = []
                    ts = start
                    while ts <= end:
                        values.append([ts, str(round(metric_value(metric, node_idx, gpu_idx, ts), 3))])
                        ts += step
                    result.append({
                        "metric": {
                            "__name__": metric,
                            "Hostname": f"gpu-node-{node_idx:02d}",
                            "gpu": str(gpu_idx),
                            "instance": f"gpu-node-{node_idx:02d}:9400",
                        },
                        "values": values,
                    })
        self._send({"status": "success", "data": {"resultType": "matrix", "result": result}})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9090), Handler)
    print("Mock Prometheus running on http://0.0.0.0:9090")
    server.serve_forever()
