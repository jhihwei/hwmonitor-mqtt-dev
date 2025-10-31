#!/bin/bash
#
# WiFi Portal Installation Verification Script
# Check if the WiFi portal is correctly installed
#

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="/opt/wifi-portal"
SERVICE_NAME="wifi-portal"

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  WiFi Portal Installation Checker     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Counter for checks
TOTAL=0
PASSED=0
FAILED=0
WARNINGS=0

check() {
    TOTAL=$((TOTAL + 1))
    if eval "$1"; then
        echo -e "${GREEN}✓${NC} $2"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "${RED}✗${NC} $2"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

warn() {
    WARNINGS=$((WARNINGS + 1))
    echo -e "${YELLOW}⚠${NC} $1"
}

info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check installation directory
echo -e "${BLUE}Checking installation...${NC}"
check "[ -d '$INSTALL_DIR' ]" "Installation directory exists"
check "[ -d '$INSTALL_DIR/venv' ]" "Virtual environment exists"
check "[ -f '$INSTALL_DIR/wifi_portal/wifi_manager.py' ]" "WiFi manager module exists"
check "[ -f '$INSTALL_DIR/wifi_portal/webui/app.py' ]" "Web application exists"
echo ""

# Check Python environment
echo -e "${BLUE}Checking Python environment...${NC}"
check "[ -x '$INSTALL_DIR/venv/bin/python' ]" "Python interpreter available"
if [ -x "$INSTALL_DIR/venv/bin/python" ]; then
    PYTHON_VERSION=$("$INSTALL_DIR/venv/bin/python" --version 2>&1)
    info "Python version: $PYTHON_VERSION"
fi

check "$INSTALL_DIR/venv/bin/pip show uvicorn >/dev/null 2>&1" "uvicorn installed"
check "$INSTALL_DIR/venv/bin/pip show fastapi >/dev/null 2>&1" "fastapi installed"
check "$INSTALL_DIR/venv/bin/pip show jinja2 >/dev/null 2>&1" "jinja2 installed"
echo ""

# Check systemd service
echo -e "${BLUE}Checking systemd service...${NC}"
check "[ -f '/etc/systemd/system/${SERVICE_NAME}.service' ]" "Service file exists"
check "systemctl is-enabled ${SERVICE_NAME} >/dev/null 2>&1 || systemctl list-unit-files | grep -q ${SERVICE_NAME}" "Service is registered"

if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo -e "${GREEN}✓${NC} Service is running"
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
else
    echo -e "${YELLOW}⚠${NC} Service is not running"
    WARNINGS=$((WARNINGS + 1))
    info "Start with: sudo systemctl start ${SERVICE_NAME}"
fi

if systemctl is-enabled --quiet ${SERVICE_NAME}; then
    echo -e "${GREEN}✓${NC} Service is enabled (auto-start on boot)"
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
else
    echo -e "${YELLOW}⚠${NC} Service is not enabled"
    WARNINGS=$((WARNINGS + 1))
    info "Enable with: sudo systemctl enable ${SERVICE_NAME}"
fi
echo ""

# Check system dependencies
echo -e "${BLUE}Checking system dependencies...${NC}"
check "command -v nmcli >/dev/null 2>&1" "nmcli (NetworkManager) available"
check "command -v wpa_cli >/dev/null 2>&1" "wpa_cli (wpa_supplicant) available"
check "[ -f '/etc/wpa_supplicant/wpa_supplicant.conf' ]" "wpa_supplicant config exists"
echo ""

# Check AP mode (optional)
echo -e "${BLUE}Checking AP mode configuration (optional)...${NC}"
if [ -f "/etc/hostapd/hostapd.conf" ]; then
    echo -e "${GREEN}✓${NC} hostapd configured"
    if systemctl is-active --quiet hostapd; then
        echo -e "${GREEN}✓${NC} hostapd is running"
    else
        warn "hostapd is not running"
    fi
else
    warn "AP mode not configured (run setup-ap-mode.sh if needed)"
fi

if [ -f "/etc/dnsmasq.conf" ] && grep -q "WiFi Portal" /etc/dnsmasq.conf 2>/dev/null; then
    echo -e "${GREEN}✓${NC} dnsmasq configured for WiFi Portal"
    if systemctl is-active --quiet dnsmasq; then
        echo -e "${GREEN}✓${NC} dnsmasq is running"
    else
        warn "dnsmasq is not running"
    fi
else
    warn "dnsmasq not configured for WiFi Portal"
fi
echo ""

# Check network connectivity
echo -e "${BLUE}Checking network configuration...${NC}"
if command -v ip >/dev/null 2>&1; then
    WLAN_INTERFACES=$(ip link show | grep -o "wlan[0-9]" | head -1)
    if [ -n "$WLAN_INTERFACES" ]; then
        echo -e "${GREEN}✓${NC} WiFi interface found: $WLAN_INTERFACES"
        IP_ADDR=$(ip addr show "$WLAN_INTERFACES" | grep "inet " | awk '{print $2}' | cut -d/ -f1)
        if [ -n "$IP_ADDR" ]; then
            info "IP address: $IP_ADDR"
            info "Portal URL: http://${IP_ADDR}:8080"
        fi
    else
        warn "No WiFi interface found"
    fi
fi
echo ""

# Summary
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           Check Summary                ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo -e "Total checks:  ${TOTAL}"
echo -e "${GREEN}Passed:        ${PASSED}${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed:        ${FAILED}${NC}"
fi
if [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}Warnings:      ${WARNINGS}${NC}"
fi
echo ""

# Exit status
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}Installation verification completed successfully!${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    if ! systemctl is-active --quiet ${SERVICE_NAME}; then
        echo "  1. Start the service: sudo systemctl start ${SERVICE_NAME}"
    fi
    if ! systemctl is-enabled --quiet ${SERVICE_NAME}; then
        echo "  2. Enable auto-start: sudo systemctl enable ${SERVICE_NAME}"
    fi
    echo "  3. Access portal at: http://<raspberry-pi-ip>:8080"
    exit 0
else
    echo -e "${RED}Installation verification failed!${NC}"
    echo ""
    echo -e "${YELLOW}Please check the failed items above and:${NC}"
    echo "  1. Re-run the installation: sudo ./install.sh"
    echo "  2. Check logs: sudo journalctl -u ${SERVICE_NAME} -n 50"
    echo "  3. See DEPLOYMENT.md for troubleshooting"
    exit 1
fi
