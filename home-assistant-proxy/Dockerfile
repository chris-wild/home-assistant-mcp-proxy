ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.11-alpine3.19
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
WORKDIR /app

# Install Python deps
COPY mcp_server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy application (tests and dev files excluded via .dockerignore)
COPY run.sh /run.sh
COPY mcp_server /app/mcp_server

RUN chmod a+x /run.sh

CMD ["/run.sh"]
