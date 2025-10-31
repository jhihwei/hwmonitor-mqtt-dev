#!/bin/bash
#
# WiFi Portal Installation Script for Raspberry Pi OS
# This script installs and configures the WiFi portal for native execution
#

set -e

# Configuration
INSTALL_DIR="/opt/wifi-portal"
VENV_DIR="${INSTALL_DIR}/venv"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Raspberry Pi WiFi Portal Installer   ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERROR: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Detect Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo && ! grep -q "BCM" /proc/cpuinfo; then
    echo -e "${YELLOW}WARNING: This doesn't appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Install system dependencies
echo -e "${GREEN}[1/6] Installing system dependencies...${NC}"
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    network-manager \
    wpasupplicant \
    wireless-tools \
    git

# Create installation directory
echo -e "${GREEN}[2/6] Creating installation directory...${NC}"
mkdir -p "${INSTALL_DIR}"

# Copy project files
echo -e "${GREEN}[3/6] Copying project files...${NC}"

# Create proper package structure
mkdir -p "${INSTALL_DIR}/wifi_portal"

# Copy Python package files
cp "${PROJECT_DIR}/wifi_manager.py" "${INSTALL_DIR}/wifi_portal/"
cp "${PROJECT_DIR}/__init__.py" "${INSTALL_DIR}/wifi_portal/"
cp -r "${PROJECT_DIR}/webui" "${INSTALL_DIR}/wifi_portal/"

# Copy configuration and scripts
cp "${PROJECT_DIR}"/*.sh "${INSTALL_DIR}/" 2>/dev/null || true
cp "${PROJECT_DIR}"/*.service "${INSTALL_DIR}/" 2>/dev/null || true
cp "${PROJECT_DIR}/"*.md "${INSTALL_DIR}/" 2>/dev/null || true
cp "${PROJECT_DIR}/setup.py" "${INSTALL_DIR}/" 2>/dev/null || true
cp "${PROJECT_DIR}/MANIFEST.in" "${INSTALL_DIR}/" 2>/dev/null || true

# Create virtual environment
echo -e "${GREEN}[4/6] Creating Python virtual environment...${NC}"
python3 -m venv "${VENV_DIR}"

# Install Python dependencies
echo -e "${GREEN}[5/6] Installing Python dependencies...${NC}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install uvicorn fastapi jinja2 python-multipart

# Install and configure systemd service
echo -e "${GREEN}[6/6] Installing systemd service...${NC}"
cp "${INSTALL_DIR}/wifi-portal.service" /etc/systemd/system/
systemctl daemon-reload

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║      Installation Complete! ✓          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo ""
echo -e "1. ${YELLOW}Configure AP Mode (Optional):${NC}"
echo -e "   sudo ${INSTALL_DIR}/setup-ap-mode.sh"
echo ""
echo -e "2. ${YELLOW}Enable and start the service:${NC}"
echo -e "   sudo systemctl enable wifi-portal"
echo -e "   sudo systemctl start wifi-portal"
echo ""
echo -e "3. ${YELLOW}Check service status:${NC}"
echo -e "   sudo systemctl status wifi-portal"
echo ""
echo -e "4. ${YELLOW}View logs:${NC}"
echo -e "   sudo journalctl -u wifi-portal -f"
echo ""
echo -e "${BLUE}Service management:${NC}"
echo -e "   sudo ${INSTALL_DIR}/portal-service.sh {start|stop|restart|status|logs}"
echo ""
echo -e "${BLUE}Portal access:${NC}"
echo -e "   http://$(hostname -I | awk '{print $1}'):8080"
echo -e "   (or http://192.168.4.1:8080 in AP mode)"
echo ""
