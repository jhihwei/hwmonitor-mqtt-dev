#!/bin/bash
#
# WiFi Portal Service Management Script
# Manage the WiFi configuration portal service
#

set -e

SERVICE_NAME="wifi-portal"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}ERROR: This script must be run as root${NC}"
        exit 1
    fi
}

# Show usage
usage() {
    cat <<EOF
Usage: $0 {start|stop|restart|status|enable|disable|logs|install|uninstall}

Commands:
    start       Start the WiFi portal service
    stop        Stop the WiFi portal service
    restart     Restart the WiFi portal service
    status      Show service status
    enable      Enable service to start on boot
    disable     Disable service from starting on boot
    logs        Show service logs (tail -f)
    install     Install the service
    uninstall   Uninstall the service

EOF
    exit 1
}

# Install service
install_service() {
    echo -e "${GREEN}Installing WiFi Portal service...${NC}"

    # Copy service file
    if [ ! -f "${SCRIPT_DIR}/wifi-portal.service" ]; then
        echo -e "${RED}ERROR: wifi-portal.service not found in ${SCRIPT_DIR}${NC}"
        exit 1
    fi

    cp "${SCRIPT_DIR}/wifi-portal.service" "/etc/systemd/system/${SERVICE_NAME}.service"

    # Reload systemd
    systemctl daemon-reload

    echo -e "${GREEN}Service installed successfully${NC}"
    echo "Use '$0 enable' to enable auto-start on boot"
    echo "Use '$0 start' to start the service now"
}

# Uninstall service
uninstall_service() {
    echo -e "${YELLOW}Uninstalling WiFi Portal service...${NC}"

    # Stop and disable service
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true

    # Remove service file
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"

    # Reload systemd
    systemctl daemon-reload

    echo -e "${GREEN}Service uninstalled successfully${NC}"
}

# Start service
start_service() {
    echo -e "${GREEN}Starting WiFi Portal service...${NC}"
    systemctl start "${SERVICE_NAME}"
    systemctl status "${SERVICE_NAME}" --no-pager
}

# Stop service
stop_service() {
    echo -e "${YELLOW}Stopping WiFi Portal service...${NC}"
    systemctl stop "${SERVICE_NAME}"
}

# Restart service
restart_service() {
    echo -e "${YELLOW}Restarting WiFi Portal service...${NC}"
    systemctl restart "${SERVICE_NAME}"
    systemctl status "${SERVICE_NAME}" --no-pager
}

# Show status
show_status() {
    systemctl status "${SERVICE_NAME}" --no-pager
}

# Enable service
enable_service() {
    echo -e "${GREEN}Enabling WiFi Portal service...${NC}"
    systemctl enable "${SERVICE_NAME}"
    echo "Service will start automatically on boot"
}

# Disable service
disable_service() {
    echo -e "${YELLOW}Disabling WiFi Portal service...${NC}"
    systemctl disable "${SERVICE_NAME}"
    echo "Service will not start automatically on boot"
}

# Show logs
show_logs() {
    echo -e "${GREEN}Showing WiFi Portal logs (Ctrl+C to exit)...${NC}"
    journalctl -u "${SERVICE_NAME}" -f
}

# Main
case "${1:-}" in
    install)
        check_root
        install_service
        ;;
    uninstall)
        check_root
        uninstall_service
        ;;
    start)
        check_root
        start_service
        ;;
    stop)
        check_root
        stop_service
        ;;
    restart)
        check_root
        restart_service
        ;;
    status)
        show_status
        ;;
    enable)
        check_root
        enable_service
        ;;
    disable)
        check_root
        disable_service
        ;;
    logs)
        show_logs
        ;;
    *)
        usage
        ;;
esac

exit 0
