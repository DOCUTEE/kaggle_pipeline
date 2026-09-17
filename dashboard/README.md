# Dashboard

## iTViec Dashboard → Grafana

The iTViec dashboard is now served by **Grafana** (see `infra/`).

To load data and view dashboards:

```bash
# Start services
cd infra && docker compose up -d

# Process and load data
python -m pipeline.build process itviec --data-dir data/itviec_v4
python -m pipeline.db load itviec --csv data/itviec_v4/dashboard/processed_jobs.csv

# Open Grafana
open http://localhost:3000/d/itviec-overview
```

## TopCV Dashboard → Streamlit

`app.py` is a Streamlit app for TopCV job data (separate from Grafana).

```bash
streamlit run dashboard/app.py
```
