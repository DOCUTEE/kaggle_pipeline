#!/bin/bash
# Server-side autonomous deploy finisher (Airflow-only, no cron).
# Chạy 1 lần trên server: nohup sh deploy/finish_server.sh > /tmp/finish.out 2>&1 &
# Tiến trình ghi vào /tmp/deploy_finish.log — xem bằng: tail -f /tmp/deploy_finish.log
set -u
LOG=/tmp/deploy_finish.log
REPO=/mnt/kaggle_data/kaggle_pipeline
: > "$LOG"
say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

say "1/6 perms..."
chmod -R a+rX "$REPO/dags" "$REPO/pipeline" "$REPO/infra" 2>>"$LOG"
chmod -R a+rwX "$REPO/data" 2>>"$LOG"
say "perms done"

say "2/6 compose up..."
cd "$REPO/infra" && docker compose up -d >>"$LOG" 2>&1
say "compose up exit=$?"

say "3/6 chờ scheduler parse DAG (tối đa ~12 phút)..."
for i in $(seq 1 48); do
  if docker exec kaggle_airflow_scheduler airflow dags list 2>/dev/null | grep -q jobs_daily; then
    say "scheduler OK (lần $i)"
    break
  fi
  sleep 15
done

say "4/6 unpause + trigger..."
docker exec kaggle_airflow_scheduler airflow dags unpause jobs_daily >>"$LOG" 2>&1
docker exec kaggle_airflow_scheduler airflow dags trigger jobs_daily >>"$LOG" 2>&1
say "triggered"

say "5/6 deps check..."
docker exec kaggle_airflow_scheduler python -c "import pandas, kaggle; print('deps OK')" >>"$LOG" 2>&1

say "6/6 dashboard (Grafana) + don Streamlit cu..."
pkill -f "streamlit run" 2>/dev/null || true
docker compose -f "$REPO/infra/docker-compose.yml" up -d >>"$LOG" 2>&1
sleep 10
curl -s -o /dev/null -w "grafana HTTP %{http_code}\n" --max-time 10 http://localhost:3000/api/health | tee -a "$LOG"
curl -s -o /dev/null -w "airflow HTTP %{http_code}\n" --max-time 10 http://localhost:8080/health | tee -a "$LOG"

say "DONE — Airflow UI: http://100.80.131.68:8080 | Grafana: http://100.80.131.68:3000 (query Postgres)"
