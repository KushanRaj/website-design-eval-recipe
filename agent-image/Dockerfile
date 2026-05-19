FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

SHELL ["/bin/bash", "-lc"]

ENV PATH="/root/.local/bin:${PATH}" \
    PYTHONUNBUFFERED=1

WORKDIR /tmp

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates bash && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code once at image-build time. Runtime Harbor trials should use
# the preinstalled agent wrapper, which only verifies this binary exists.
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- && \
    claude --version

WORKDIR /app
RUN mkdir -p /app/site
