#!/bin/bash

# Script calls sudo itself so it should not be run as root
if [ "$EUID" == 0 ]; then
    echo "Do not run this script as root!"
    exit 1
fi

arg_new=0
arg_packages=0
arg_venv=0
arg_frp=0
arg_sensors=0
arg_processor=0

for arg in "$@"; do
    if [[ "$arg" == "--new" ]]; then
        arg_new=1
    elif [[ "$arg" == "--packages" ]]; then
        arg_packages=1
    elif [[ "$arg" == "--venv" ]]; then
        arg_venv=1
    elif [[ "$arg" == "--frp" ]]; then
        arg_frp=1
    elif [[ "$arg" == "--sensors" ]]; then
        arg_sensors=1
    elif [[ "$arg" == "--processor" ]]; then
        arg_processor=1
    fi
done

#
# Set up Environment
#
THIS_HOSTNAME=$(hostname)
THIS_LOCATION="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

cd $THIS_LOCATION
source .env

#
# Create DIRS
#
if [[ $arg_new -eq 1 ]]; then
    mkdir -p $PAROS_DATA_LOCATION
    mkdir -p $PAROS_FRP_LOCATION
fi

#
# Install APT Packages
#
if [[ $arg_new -eq 1 ]] || [[ $arg_packages -eq 1 ]]; then
    sudo apt install python3-venv python3-dev prometheus-node-exporter
fi

#
# Python Setup
#
if [[ $arg_new -eq 1 ]] || [[ $arg_venv -eq 1 ]]; then
    python3 -m venv $PAROS_VENV_LOCATION
    source $PAROS_VENV_LOCATION/bin/activate
    pip install -r requirements.txt
fi

#
# FRPC
#
if [[ $arg_new -eq 1 ]] || [[ $arg_frp -eq 1 ]]; then
    FRP_DOWNLOAD="https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_arm64.tar.gz"
    wget -nv $FRP_DOWNLOAD -O /tmp/frp.tar.gz
    tar -xf /tmp/frp.tar.gz -C /tmp
    sudo cp /tmp/frp*/frpc /usr/local/bin/
    sudo chmod +x /usr/local/bin/frpc
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

    sudo tee /etc/systemd/system/frpc.service > /dev/null << EOF
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
fi

#
# Sensor Daemons
#
if [[ $arg_new -eq 1 ]] || [[ $arg_sensors -eq 1 ]]; then
    jq -c '.sensors[]' sensor_configs/$THIS_HOSTNAME.json | while read -r sensor; do
        driver=$(echo "$sensor" | jq -r '.driver')
        sensor_id=$(echo "$sensor" | jq -r '.sensor_id')
        args=$(echo "$sensor" | jq -r '.args')

        sudo tee /etc/systemd/system/paros-sampler-$sensor_id.service > /dev/null << EOF
[Unit]
Description=Paros Sampler $sensor_id
After=network-online.target,time-sync.target
Wants=network-online.target,time-sync.target

[Service]
WorkingDirectory=$THIS_LOCATION
ExecStart=$PAROS_VENV_LOCATION/bin/python $THIS_LOCATION/paros_sensors/$driver $sensor_id $args
Restart=always
RestartSec=10
User=pi

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable paros-sampler-$sensor_id.service
    done
fi

#
# Processor Daemon
#
if [[ $arg_new -eq 1 ]] || [[ $arg_processor -eq 1 ]]; then
    sudo sudo tee /etc/systemd/system/paros-processor.service > /dev/null << EOF
[Unit]
Description=Paros Processor
After=network-online.target,time-sync.target
Wants=network-online.target,time-sync.target

[Service]
WorkingDirectory=$THIS_LOCATION
ExecStart=$PAROS_VENV_LOCATION/bin/python $THIS_LOCATION/processor.py
Restart=always
RestartSec=10
User=pi

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable paros-processor.service

    echo "DONE. Reboot node!"
fi
