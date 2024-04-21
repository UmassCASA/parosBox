#!/bin/bash

if [ "$EUID" == 0 ]; then
    echo "Do not run this script as root!"
    exit 1
fi

#
# VARS
#
FRP_DOWNLOAD="https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_arm64.tar.gz"
THIS_HOSTNAME=$(hostname)

# Switch to current dir if not already
THIS_LOCATION=$(dirname "$0")
cd $THIS_LOCATION
source .env

#
# Create DIRS
#
mkdir -p $PAROS_DATA_LOCATION
mkdir -p $PAROS_FRP_LOCATION

#
# Install APT Packages
#
sudo apt install python3-venv python3-dev

#
# Python Setup
#
python3 -m venv $PAROS_VENV_LOCATION
source $PAROS_VENV_LOCATION/bin/activate
pip install -r requirements.txt

#
# Prometheus
#
sudo apt install prometheus-node-exporter
sudo systemctl enable prometheus-node-exporter

#
# FRPC
#
wget -nv $FRP_DOWNLOAD -O /tmp/frp.tar.gz
tar -xf /tmp/frp.tar.gz -C /tmp
cp /tmp/frp*/frpc /usr/local/bin/
chmod +x /usr/local/bin/frpc
rm -rf /tmp/frp*

cat > $PAROS_FRP_LOCATION/run.toml << EOF
serverAddr = "$PAROS_FRP_HOST"
serverPort = $PAROS_FRP_PORT
auth.token = "$PAROS_FRP_TOKEN"
[[proxies]]
name = "${THIS_HOSTNAME}_ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = $((10000 + $PAROS_FRP_OFFSET))
[[proxies]]
name = "${THIS_HOSTNAME}_prometheus"
type = "tcp"
localIP = "127.0.0.1"
localPort = 9100
remotePort = $((11000 + $PAROS_FRP_OFFSET))
EOF

sudo cat > /etc/systemd/system/frpc.service << EOF
[Unit]
Description=FRPC Daemon
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=frpc --config=$PAROS_FRP_LOCATION/run.toml
Restart=always
RestartSec=10
User=pi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable frpc.service

#
# Influx
#
wget -nv https://download.influxdata.com/influxdb/releases/influxdb2-client-2.7.5-linux-arm64.tar.gz /tmp/influx.tar.gz
tar -xf /tmp/influx.tar.gz -C /tmp
sudo cp /tmp/influx /usr/local/bin/
chmod +x /usr/local/bin/influx
rm -rf /tmp/influx*

#
# Sensor Daemons
#
while read line; do
    if [ -n "$line" ]; then
        cur_sensor_id=$(echo "$line" | cut -d' ' -f2)

        sudo cat > /etc/systemd/system/paros-$cur_sensor_id.service << EOF
[Unit]
Description=Paros Sampler $cur_sensor_id
After=network-online.target,time-sync.target
Wants=network-online.target,time-sync.target

[Service]
WorkingDirectory=/home/pi/parosBox
ExecStart=$PAROS_VENV_LOCATION/bin/python $THIS_LOCATION/paros_sensors/$line
Restart=always
RestartSec=10
User=pi

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable paros-$cur_sensor_id.service
    fi
done < sensor_configs/$DEV_HOSTNAME.txt

echo "DONE. Reboot node!"
