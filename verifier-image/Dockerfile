FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

ARG WDE_DREAMSIM_TYPE=ensemble
ARG WDE_PRELOAD_MODELS=1
ARG WDE_VERIFY_MODEL_LOAD=1

ENV PYTHONUNBUFFERED=1 \
    WDE_REPO_ROOT=/opt/wde \
    WDE_DREAMSIM_CACHE_DIR=/opt/wde/models/dreamsim \
    WDE_DREAMSIM_DEVICE=cpu \
    WDE_VISUAL_BLOCK_DEVICE=cpu \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONPATH=/opt/wde

WORKDIR /opt/wde

COPY verifier-image/requirements.txt /tmp/wde-requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch==2.12.0+cpu" \
      "torchvision==0.27.0+cpu" && \
    python -m pip install --no-cache-dir -r /tmp/wde-requirements.txt

COPY research/source-repos/dreamsim /opt/wde/research/source-repos/dreamsim
COPY research/source-repos/naturalcc /opt/wde/research/source-repos/naturalcc
COPY verifier-image/setup_models.py /opt/wde/bin/setup_models.py

RUN python -m pip install --no-cache-dir /opt/wde/research/source-repos/dreamsim

RUN if [ "$WDE_PRELOAD_MODELS" = "1" ]; then \
      verify_flag=""; \
      if [ "$WDE_VERIFY_MODEL_LOAD" = "1" ]; then verify_flag="--verify-load"; fi; \
      python /opt/wde/bin/setup_models.py \
        --dreamsim-cache-dir "$WDE_DREAMSIM_CACHE_DIR" \
        --dreamsim-type "$WDE_DREAMSIM_TYPE" \
        --device cpu \
        $verify_flag; \
    fi

COPY website_design_eval /opt/wde/website_design_eval

RUN mkdir -p /app /logs/verifier /tmp/matplotlib && chmod -R a+rX /opt/wde /logs/verifier

WORKDIR /app
