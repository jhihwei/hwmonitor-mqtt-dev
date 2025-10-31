#!/bin/bash
#
# WiFi Portal Reinstallation Script
# Quick reinstall without stopping services (useful for development)
#

set -e

INSTALL_DIR="/opt/wifi-portal"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="wifi-portal"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  WiFi Portal Reinstallation           ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERROR: This script must be run as root${NC}"
    exit 1
fi

# Check if already installed
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}WiFi Portal not found at ${INSTALL_DIR}${NC}"
    echo "Please run ./install.sh first"
    exit 1
fi

# Stop service if running
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo -e "${YELLOW}Stopping ${SERVICE_NAME} service...${NC}"
    systemctl stop ${SERVICE_NAME}
    RESTART_SERVICE=true
else
    RESTART_SERVICE=false
fi

# Backup existing files
echo -e "${GREEN}Creating backup...${NC}"
BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)"
cp -r "${INSTALL_DIR}" "${BACKUP_DIR}"
echo "Backup created at: ${BACKUP_DIR}"

# Update Python package files
echo -e "${GREEN}Updating Python package files...${NC}"
rm -rf "${INSTALL_DIR}/wifi_portal"
mkdir -p "${INSTALL_DIR}/wifi_portal"

cp "${PROJECT_DIR}/wifi_manager.py" "${INSTALL_DIR}/wifi_portal/"
cp "${PROJECT_DIR}/__init__.py" "${INSTALL_DIR}/wifi_portal/"
cp -r "${PROJECT_DIR}/webui" "${INSTALL_DIR}/wifi_portal/"

# Update scripts and configuration
echo -e "${GREEN}Updating scripts and configuration...${NC}"
cp "${PROJECT_DIR}"/*.sh "${INSTALL_DIR}/" 2>/dev/null || true
cp "${PROJECT_DIR}"/*.service "${INSTALL_DIR}/" 2>/dev/null || true
cp "${PROJECT_DIR}/"*.md "${INSTALL_DIR}/" 2>/dev/null || true

# Update systemd service file
if [ -f "${INSTALL_DIR}/wifi-portal.service" ]; then
    cp "${INSTALL_DIR}/wifi-portal.service" "/etc/systemd/system/"
    systemctl daemon-reload
fi

# Update dependencies
echo -e "${GREEN}Updating Python dependencies...${NC}"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip -q
"${INSTALL_DIR}/venv/bin/pip" install --upgrade uvicorn fastapi jinja2 python-multipart -q

# Restart service if it was running
if [ "$RESTART_SERVICE" = true ]; then
    echo -e "${GREEN}Restarting ${SERVICE_NAME} service...${NC}"
    systemctl start ${SERVICE_NAME}
    sleep 2
    systemctl status ${SERVICE_NAME} --no-pager
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      Reinstallation Complete! ✓        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Backup location:${NC} ${BACKUP_DIR}"
echo ""
if [ "$RESTART_SERVICE" = true ]; then
    echo -e "${GREEN}Service is running${NC}"
else
    echo -e "${YELLOW}Service was not running. Start with:${NC}"
    echo "  sudo systemctl start ${SERVICE_NAME}"
fi
echo ""
