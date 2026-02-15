#!/bin/bash
set -e

echo "--- Installing OPA v0.46.0 ---"
# Download OPA to a location in the PATH
sudo curl -L -o /usr/local/bin/opa https://openpolicyagent.org/downloads/v0.46.0/opa_linux_amd64_static
sudo chmod 755 /usr/local/bin/opa

#  Install LocalStack 
echo "--- Installing LocalStack ---"
/opt/conda/bin/pip install localstack

echo "--- Setting up Conda Environment ---"
# Initialize conda for the shell
source /opt/conda/etc/profile.d/conda.sh

# Update the 'base' environment with dependencies from environment.yml
# We use the absolute path just to be safe
/opt/conda/bin/conda env update -n base -f environment.yml


echo "--- Setup Complete ---"