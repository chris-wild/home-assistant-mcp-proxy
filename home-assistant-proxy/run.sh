#!/usr/bin/with-contenv bashio
set -euo pipefail

HA_URL=$(bashio::config 'home_assistant_url')
ACCESS_TOKEN=$(bashio::config 'access_token')
ALLOWED_ENTITIES=$(bashio::config 'allowed_entities')
ALLOWED_DOMAINS=$(bashio::config 'allowed_domains')
LOG_LEVEL=$(bashio::config 'log_level')
CONFIRM_DOMAINS=$(bashio::config 'confirmation_required_for')

export MCP_HOME_ASSISTANT_URL="$HA_URL"
export MCP_HOME_ASSISTANT_TOKEN="$ACCESS_TOKEN"
export MCP_ALLOWED_ENTITIES="$ALLOWED_ENTITIES"
export MCP_ALLOWED_DOMAINS="$ALLOWED_DOMAINS"
export MCP_LOG_LEVEL="$LOG_LEVEL"
export MCP_CONFIRMATION_DOMAINS="$CONFIRM_DOMAINS"

cd /app/mcp_server
exec uvicorn app.main:app --host 0.0.0.0 --port 8745
