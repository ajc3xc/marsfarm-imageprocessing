#!/bin/bash

# URL to the Miniforge installer
MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"

# Download the Miniforge installer
wget $MINIFORGE_URL -O Miniforge3.sh

# Make the installer executable
chmod +x Miniforge3.sh

# Install Miniforge (accepting the license and using the default installation directory)
./Miniforge3.sh

# Reload the shell to activate conda
exec $SHELL

# Create the environment from the provided YAML file
mamba env create --file enviornment/environment.yml

# Cleanup: remove the installer
rm Miniforge3.sh
