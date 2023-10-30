#!/bin/bash

# Switch to current dir if not already
cd "$(dirname "$0")"

# Install system packages
sudo apt install python3-venv

# Create python venv here
python3 -m venv venv

# Activate venv
source ./venv/bin/activate

# Install python packages
pip install -r requirements.txt
