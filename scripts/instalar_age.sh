#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends python3 curl ca-certificates
curl --fail --silent --show-error --location \
  https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz \
  --output /tmp/age.tar.gz
echo 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10  /tmp/age.tar.gz' | sha256sum --check -
tar -xzf /tmp/age.tar.gz -C /tmp
install /tmp/age/age /usr/local/bin/age
install /tmp/age/age-keygen /usr/local/bin/age-keygen
