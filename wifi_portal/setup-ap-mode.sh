#!/bin/bash
#
# Setup Raspberry Pi as WiFi Access Point with captive portal
# This script configures hostapd and dnsmasq for AP mode
#

set -e

INTERFACE="${WIFI_INTERFACE:-wlan0}"
SSID="${AP_SSID:-RasPi-Setup}"
PASSWORD="${AP_PASSWORD:-raspberry}"
IP_ADDRESS="192.168.4.1"
DHCP_RANGE_START="192.168.4.2"
DHCP_RANGE_END="192.168.4.20"
PORTAL_PORT="${PORTAL_PORT:-8080}"

echo "=== Raspberry Pi WiFi Portal AP Setup ==="
echo "Interface: $INTERFACE"
echo "SSID: $SSID"
echo "IP Address: $IP_ADDRESS"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Install required packages
echo "Installing required packages..."
apt-get update
apt-get install -y hostapd dnsmasq iptables-persistent

# Stop services during configuration
systemctl stop hostapd
systemctl stop dnsmasq

# Backup existing configurations
echo "Backing up existing configurations..."
[ -f /etc/hostapd/hostapd.conf ] && cp /etc/hostapd/hostapd.conf /etc/hostapd/hostapd.conf.bak
[ -f /etc/dnsmasq.conf ] && cp /etc/dnsmasq.conf /etc/dnsmasq.conf.bak
[ -f /etc/dhcpcd.conf ] && cp /etc/dhcpcd.conf /etc/dhcpcd.conf.bak

# Configure static IP for wlan0
echo "Configuring static IP..."
cat >> /etc/dhcpcd.conf <<EOF

# WiFi Portal AP Mode Configuration
interface $INTERFACE
    static ip_address=${IP_ADDRESS}/24
    nohook wpa_supplicant
EOF

# Configure hostapd
echo "Configuring hostapd..."
cat > /etc/hostapd/hostapd.conf <<EOF
# WiFi Portal AP Configuration
interface=$INTERFACE
driver=nl80211
ssid=$SSID
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASSWORD
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Point hostapd to config file
sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

# Configure dnsmasq
echo "Configuring dnsmasq..."
cat > /etc/dnsmasq.conf <<EOF
# WiFi Portal DNS Configuration
interface=$INTERFACE
dhcp-range=$DHCP_RANGE_START,$DHCP_RANGE_END,255.255.255.0,24h

# DNS for captive portal
address=/#/${IP_ADDRESS}

# Disable DNS for external queries
no-resolv
no-poll

# Log queries for debugging
log-queries
log-dhcp

# Captive portal detection
address=/connectivitycheck.gstatic.com/${IP_ADDRESS}
address=/clients3.google.com/${IP_ADDRESS}
address=/captive.apple.com/${IP_ADDRESS}
address=/www.msftconnecttest.com/${IP_ADDRESS}
EOF

# Enable IP forwarding (optional, for internet sharing)
echo "Enabling IP forwarding..."
sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf
sysctl -p

# Configure iptables for captive portal redirect
echo "Configuring iptables..."
iptables -t nat -F
iptables -F
iptables -t nat -A PREROUTING -i $INTERFACE -p tcp --dport 80 -j DNAT --to-destination ${IP_ADDRESS}:${PORTAL_PORT}
iptables -t nat -A PREROUTING -i $INTERFACE -p tcp --dport 443 -j DNAT --to-destination ${IP_ADDRESS}:${PORTAL_PORT}
iptables -A FORWARD -i $INTERFACE -j ACCEPT

# Save iptables rules
netfilter-persistent save

# Enable and start services
echo "Enabling services..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

echo ""
echo "=== Configuration Complete ==="
echo ""
echo "AP Mode will be activated on next reboot, or run:"
echo "  sudo systemctl restart dhcpcd"
echo "  sudo systemctl restart hostapd"
echo "  sudo systemctl restart dnsmasq"
echo ""
echo "Access point details:"
echo "  SSID: $SSID"
echo "  Password: $PASSWORD"
echo "  Portal URL: http://${IP_ADDRESS}:${PORTAL_PORT}"
echo ""
