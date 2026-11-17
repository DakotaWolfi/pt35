#!/bin/bash
# FMI Print Station for Orange Pi Zero 3W. Run once with sudo.
set -euo pipefail
test "$(id -u)" = 0 || { echo "Run: sudo bash install_orangepi.sh"; exit 1; }
APP=/home/jenna/pt35/print_station
test -f "$APP/app.py" || { echo "App missing at $APP"; exit 1; }
apt-get install -y python3-pil python3-libgpiod python3-spidev git
mkdir -p /home/jenna/.local/state/fmi-print-station
chown -R jenna:jenna /home/jenna/.local/state/fmi-print-station
cat > /etc/systemd/system/fmi-print-station.service <<'EOF'
[Unit]
Description=FMI Print Station web app
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jenna
Group=jenna
WorkingDirectory=/home/jenna/pt35/print_station
ExecStart=/usr/bin/python3 /home/jenna/pt35/print_station/app.py
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/fmi-print-display.service <<'EOF'
[Unit]
Description=FMI E-paper status display
After=fmi-print-station.service
Wants=fmi-print-station.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/jenna/pt35/print_station
ExecStart=/usr/bin/python3 /home/jenna/pt35/print_station/display_epaper.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/fmi-print-update.service <<'EOF'
[Unit]
Description=Check GitHub for FMI Print Station updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=jenna
Group=jenna
Environment=HOME=/home/jenna
WorkingDirectory=/home/jenna/pt35
ExecStart=/bin/bash /home/jenna/pt35/print_station/auto_update.sh
NoNewPrivileges=true
EOF
cat > /etc/systemd/system/fmi-print-update.timer <<'EOF'
[Unit]
Description=Periodically check for Print Station updates

[Timer]
OnBootSec=5min
OnUnitInactiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/fmi-print-restart.path <<'EOF'
[Unit]
Description=Watch for deployed Print Station Git revision

[Path]
PathChanged=/home/jenna/.local/state/fmi-print-station/revision
Unit=fmi-print-restart.service

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/fmi-print-restart.service <<'EOF'
[Unit]
Description=Restart Print Station following a Git update
After=fmi-print-update.service

[Service]
Type=oneshot
ExecStart=/bin/systemctl try-restart fmi-print-station.service
ExecStart=/bin/systemctl try-restart fmi-print-display.service
EOF
systemctl daemon-reload
# Stop manual app.py process before starting this service; otherwise port 8767 is already bound.
systemctl enable fmi-print-station.service fmi-print-display.service
systemctl enable --now fmi-print-restart.path fmi-print-update.timer
echo "Services installed; stop any manual 'python3 app.py' first."
echo "Then: sudo systemctl start fmi-print-station fmi-print-display"
echo "Updater: sudo systemctl start fmi-print-update.service"
