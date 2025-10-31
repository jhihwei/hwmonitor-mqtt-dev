#!/bin/bash
#
# Development server launcher for WiFi Portal
# Run this script to test the portal without installing as a service
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}WiFi Portal - Development Server${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}WARNING: Not running as root${NC}"
    echo "Some WiFi management features may not work without root privileges"
    echo ""
fi

# Create venv if not exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Install/update dependencies
echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q uvicorn fastapi jinja2 python-multipart

# Set Python path
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

echo ""
echo -e "${GREEN}Starting development server...${NC}"
echo "URL: http://localhost:${PORT}"
echo "Press Ctrl+C to stop"
echo ""

# Run uvicorn
"$VENV_DIR/bin/uvicorn" wifi_portal.webui.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload \
    --log-level info
