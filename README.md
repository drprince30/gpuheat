
# FCCT GPU Cascade Guard V3

Deployable commercial shadow-monitoring system for GPU thermal/workload cascade-risk analysis.

V3 adds over V2:

- SQLite persistent history
- optional basic authentication
- Prometheus/DCGM polling with optional auto-refresh
- operator recommendation engine
- saved runs / alert history / recommendation history
- Docker Compose deployment
- Helm chart starter
- Grafana dashboard starter
- mock Prometheus for local demos
- HTML operations/pilot report export

## Run with Docker Compose

```bash
docker compose up --build
```

Open:

```text
http://localhost:8501
```

For Prometheus/DCGM mode inside Docker:

```text
Prometheus URL = http://mock-prometheus:9090
```

## Run locally

```bash
pip install -r requirements.txt
python mock_prometheus.py
streamlit run app.py
```

Then in the app use:

```text
Prometheus URL = http://localhost:9090
```

## Enable login

In Docker Compose or your environment:

```bash
FCCT_AUTH_ENABLED=true
FCCT_USERNAME=admin
FCCT_PASSWORD=your-secure-password
```

## Helm install

Build and push your image first, then:

```bash
helm install fcct-guard ./helm/fcct-gpu-cascade-guard \
  --set image.repository=your-registry/fcct-gpu-cascade-guard \
  --set image.tag=v3 \
  --set prometheus.url=http://prometheus-server:9090 \
  --set auth.username=admin \
  --set auth.password='change-me'
```

Port forward:

```bash
kubectl port-forward svc/fcct-guard 8501:8501
```

Open:

```text
http://localhost:8501
```

## Data inputs

### CSV mode

Telemetry required:

```csv
timestamp,node_id,gpu_id,temp_c
```

Optional:

```csv
power_w,gpu_util,mem_util,fan_pct,throttle_flag,job_id,tenant_id
```

Topology recommended:

```csv
node_id,rack_id,row,col,zone
```

### Prometheus/DCGM mode

Default metric names:

```text
DCGM_FI_DEV_GPU_TEMP
DCGM_FI_DEV_POWER_USAGE
DCGM_FI_DEV_GPU_UTIL
DCGM_FI_DEV_MEM_COPY_UTIL
DCGM_FI_DEV_CLOCK_THROTTLE_REASONS
```

## What V3 is

V3 is a deployable shadow-monitoring and recommendation product.

It does:

- ingest telemetry
- calibrate S0-S5 states
- compute FCCT cascade risk
- identify risky GPU/node/rack clusters
- recommend operator actions
- compare against threshold baselines
- persist history
- export reports

It does not yet:

- automatically migrate jobs
- automatically change power limits
- automatically control cooling
- provide enterprise SSO/RBAC
- guarantee production prediction without customer validation

## V4 next

V4 should add:

- Kubernetes metadata connector
- DCGM service discovery
- real Prometheus recording rules
- role-based access
- multi-cluster support
- scheduled background polling service
- recommendation approval workflow
- optional safe automation hooks
