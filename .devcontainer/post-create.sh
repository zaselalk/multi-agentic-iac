#!/bin/bash
set -e

echo "--- Installing OPA v0.46.0 ---"
# Download OPA to a location in the PATH
sudo curl -L -o /usr/local/bin/opa https://openpolicyagent.org/downloads/v0.46.0/opa_linux_amd64_static
sudo chmod 755 /usr/local/bin/opa

# --- 2. Install AWS CLI (Manual Install) ---
echo "--- Installing AWS CLI ---"
# Download and install v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
sudo ./aws/install --update
rm -rf aws awscliv2.zip

# --- 3. Configure Dummy AWS Credentials ---
echo "--- Configuring LocalStack Credentials ---"
# Create the directory
mkdir -p ~/.aws

# Write the credentials file
echo "[default]
aws_access_key_id = test
aws_secret_access_key = test" > ~/.aws/credentials

# Write the config file
echo "[default]
region = us-east-1
output = json" > ~/.aws/config

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