# Airflow image cho pipeline — thêm Playwright + Chromium.
#
# Vì sao cần: scraper topcv chạy BÊN TRONG container (DAG jobs_daily), mà
# `_PIP_ADDITIONAL_REQUIREMENTS` chỉ cài package python — không có browser binary
# lẫn thư viện hệ thống (thiếu libs → chromium thoát với exitCode 127).
# Build sẵn ở đây để deploy lặp lại được, không phụ thuộc volume/quyền runtime.
FROM apache/airflow:2.9.3-python3.12

USER root

# PIN version: phải khớp playwright trong _PIP_ADDITIONAL_REQUIREMENTS
# (infra/docker-compose.yml) để browser đúng build mà package mong đợi.
ARG PLAYWRIGHT_VERSION=1.63.0
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# `python -m pip` chứ không phải `pip`: shim `pip` của image Airflow chặn khi
# chạy bằng root ("You are running pip as root"), còn gọi module thì không.
RUN python -m pip install --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}" \
    && python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/ms-playwright

USER airflow
