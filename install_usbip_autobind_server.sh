#!/bin/bash
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root."
  exit 1
fi

SERVICE_NAME="usbip-autobind"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
USBIPD_SERVICE_PATH="/etc/systemd/system/usbipd.service"

if ! command -v usbip &> /dev/null; then
  echo "usbip not found. Attempting to install..."
  if command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y usbip
  elif command -v dnf &> /dev/null; then
    dnf install -y usbip
  elif command -v pacman &> /dev/null; then
    pacman -Sy --noconfirm usbip
  else
    echo "Could not detect package manager. Please install usbip manually."
    exit 1
  fi
fi

# Determine the correct user home for uvx
if [ -n "$SUDO_USER" ]; then
  USER_HOME=$(eval echo ~$SUDO_USER)
else
  USER_HOME="$HOME"
fi

# Find uvx in PATH or userland
if ! command -v uvx &> /dev/null; then
  if [ -x "$USER_HOME/.local/bin/uvx" ]; then
    export PATH="$USER_HOME/.local/bin:$PATH"
  fi
fi

if ! command -v uvx &> /dev/null; then
  echo "uvx not found. Installing via pip..."
  if command -v pip3 &> /dev/null; then
    sudo -u "$SUDO_USER" pip3 install --user uvx
    export PATH="$USER_HOME/.local/bin:$PATH"
  elif command -v pip &> /dev/null; then
    sudo -u "$SUDO_USER" pip install --user uvx
    export PATH="$USER_HOME/.local/bin:$PATH"
  else
    echo "pip not found. Please install pip and rerun this script."
    exit 1
  fi
fi

# Enable kernel modules
modprobe usbip-core || true
modprobe usbip-host || true

# Create and enable usbipd systemd service if missing
if [ ! -f "$USBIPD_SERVICE_PATH" ]; then
  echo "Creating usbipd systemd service..."
  cat <<EOF > "$USBIPD_SERVICE_PATH"
[Unit]
Description=usbip host daemon
After=network.target

[Service]
Type=forking
ExecStart=/usr/sbin/usbipd -D

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable usbipd
  systemctl start usbipd
else
  systemctl start usbipd
fi

# Prompt for overrides with defaults
read -p "Socket host [0.0.0.0]: " SOCKET_HOST
SOCKET_HOST=${SOCKET_HOST:-0.0.0.0}

read -p "Socket port [65432]: " SOCKET_PORT
SOCKET_PORT=${SOCKET_PORT:-65432}

read -p "Web host [0.0.0.0]: " WEB_HOST
WEB_HOST=${WEB_HOST:-0.0.0.0}

read -p "Web port [8080]: " WEB_PORT
WEB_PORT=${WEB_PORT:-8080}

while true; do
  echo "Example whitelist: 1-1,1-2,2-1,2-2 (these are bus IDs for USB ports; use 'usbip list -l' to find yours)"
  read -p "Physical ports (comma-separated, required): " PHYSICAL_PORTS
  if [ -n "$PHYSICAL_PORTS" ]; then
    break
  fi
  echo "Physical ports are required. Please provide a comma-separated whitelist."
done
PHYSICAL_PORTS_ARG="--physical-ports $PHYSICAL_PORTS"

read -p "Assignments file path [/var/lib/usbip-autobind/assignments.json]: " ASSIGNMENTS_FILE
ASSIGNMENTS_FILE=${ASSIGNMENTS_FILE:-/var/lib/usbip-autobind/assignments.json}

# Ensure assignments file directory exists
ASSIGNMENTS_DIR=$(dirname "$ASSIGNMENTS_FILE")
mkdir -p "$ASSIGNMENTS_DIR"

# Build ExecStart command
EXEC_CMD="$USER_HOME/.local/bin/uvx --from git+https://github.com/virus-rpi/usbip-autobind@master usbip-server --socket-host $SOCKET_HOST --socket-port $SOCKET_PORT --web-host $WEB_HOST --web-port $WEB_PORT $PHYSICAL_PORTS_ARG --assignments-file $ASSIGNMENTS_FILE"

cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=usbip-autobind server
After=network.target usbipd.service
Requires=usbipd.service

[Service]
Type=simple
ExecStart=$EXEC_CMD
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

echo "Service $SERVICE_NAME installed and started."
echo "You can edit $SERVICE_PATH to change arguments later."
