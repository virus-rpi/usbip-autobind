#!/bin/bash
set -e

SERVICE_NAME="usbip-autobind"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
USBIPD_SERVICE_PATH="/etc/systemd/system/usbipd.service"
ASSIGNMENTS_DEFAULT="/var/lib/usbip-autobind/assignments.json"

# 1. Ensure uvx is installed for the current user
if ! command -v uvx &> /dev/null; then
  if [ -x "$HOME/.local/bin/uvx" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
if ! command -v uvx &> /dev/null; then
  echo "uvx not found. Installing via pip..."
  if command -v pip3 &> /dev/null; then
    pip3 install --user uvx
    export PATH="$HOME/.local/bin:$PATH"
  elif command -v pip &> /dev/null; then
    pip install --user uvx
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "pip not found. Please install pip and rerun this script."
    exit 1
  fi
fi

# 2. Prompt for config options as user
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

read -p "Assignments file path [$ASSIGNMENTS_DEFAULT]: " ASSIGNMENTS_FILE
ASSIGNMENTS_FILE=${ASSIGNMENTS_FILE:-$ASSIGNMENTS_DEFAULT}
ASSIGNMENTS_DIR=$(dirname "$ASSIGNMENTS_FILE")

# 3. System-level operations (sudo)

# Install usbip if missing
if ! command -v usbip &> /dev/null; then
  echo "usbip not found. Attempting to install..."
  if command -v apt-get &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y usbip
  elif command -v dnf &> /dev/null; then
    sudo dnf install -y usbip
  elif command -v pacman &> /dev/null; then
    sudo pacman -Sy --noconfirm usbip
  else
    echo "Could not detect package manager. Please install usbip manually."
    exit 1
  fi
fi

# Enable kernel modules
sudo modprobe usbip-core || true
sudo modprobe usbip-host || true

# Create assignments file directory
sudo mkdir -p "$ASSIGNMENTS_DIR"

# Create and enable usbipd systemd service if missing
if ! sudo test -f "$USBIPD_SERVICE_PATH"; then
  echo "Creating usbipd systemd service..."
  sudo tee "$USBIPD_SERVICE_PATH" > /dev/null <<EOF
[Unit]
Description=usbip host daemon
After=network.target

[Service]
Type=forking
ExecStart=/usr/sbin/usbipd -D

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable usbipd
  sudo systemctl start usbipd
else
  sudo systemctl start usbipd
fi

# Build ExecStart command
EXEC_CMD="$HOME/.local/bin/uvx --from git+https://github.com/virus-rpi/usbip-autobind@master usbip-server --socket-host $SOCKET_HOST --socket-port $SOCKET_PORT --web-host $WEB_HOST --web-port $WEB_PORT $PHYSICAL_PORTS_ARG --assignments-file $ASSIGNMENTS_FILE"

# Create and enable usbip-autobind systemd service
sudo tee "$SERVICE_PATH" > /dev/null <<EOF
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

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo "Service $SERVICE_NAME installed and started."
echo "You can edit $SERVICE_PATH to change arguments later."
