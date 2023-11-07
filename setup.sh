#!/bin/bash

# Switch to current dir if not already
cd "$(dirname "$0")"

# enable SPI bus
sudo raspi-config nonint do_spi 0

# make folders
mkdir -p buffer
mkdir -p data
mkdir -p logs

# Install system packages
sudo apt install python3-venv python3-dev

# Create python venv here
python3 -m venv venv

# Activate venv
source ./venv/bin/activate

# Install python packages
pip install -r requirements.txt

# Setup prometheus
sudo apt install prometheus-node-exporter
sudo systemctl enable prometheus-node-exporter

# Setup FRP
frp_download="https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_arm64.tar.gz"
wget -nv $frp_download -O /tmp/frp.tar.gz
tar -xf /tmp/frp.tar.gz -C /tmp
mkdir -p ./frpc/
cp /tmp/frp*/frpc ./frpc/
chmod +x ./frpc
rm -rf /tmp/frp*

conf_file="config/$(hostname).json"
frp_hostname=$(jq -r '.frp.host' $conf_file)
frp_port=$(jq -r '.frp.port' $conf_file)
frp_token=$(cat "secrets/FRP_TOKEN")
frp_offset=$(jq -r '.frp.offset' $conf_file)

echo "serverAddr = \"$frp_hostname\"" > frpc/run.toml
echo "serverPort = $frp_port" >> frpc/run.toml
echo "auth.token = \"$frp_token\"" >> frpc/run.toml
echo "[[proxies]]" >> frpc/run.toml
echo "name = \"paros2_ssh\"" >> frpc/run.toml
echo "type = \"tcp\"" >> frpc/run.toml
echo "localIP = \"127.0.0.1\"" >> frpc/run.toml
echo "localPort = 22" >> frpc/run.toml
remote_port=$((10000 + $frp_offset))
echo "remotePort = $remote_port" >> frpc/run.toml
echo "[[proxies]]" >> frpc/run.toml
echo "name = \"paros2_prometheus\"" >> frpc/run.toml
echo "type = \"tcp\"" >> frpc/run.toml
echo "localIP = \"127.0.0.1\"" >> frpc/run.toml
echo "localPort = 9100" >> frpc/run.toml
remote_port=$((11000 + $frp_offset))
echo "remotePort = $remote_port" >> frpc/run.toml

# Setup systemd
sudo cp systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable frpc
sudo systemctl enable parosbox

echo "DONE. Reboot node!"
