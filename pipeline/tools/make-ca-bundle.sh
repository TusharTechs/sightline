#!/bin/bash
# Builds a CA bundle that includes the machine's own trust store, so HTTPS to
# AWS and PyPI works where the network terminates TLS with its own chain.
# Without this the AWS API fails with CERTIFICATE_VERIFY_FAILED and pip times out.
set -euo pipefail
OUT="${1:-$HOME/.config/sightline-ca.pem}"
mkdir -p "$(dirname "$OUT")"
python3 -c "import certifi,shutil,sys; shutil.copyfile(certifi.where(), sys.argv[1])" "$OUT"
for kc in /System/Library/Keychains/SystemRootCertificates.keychain \
          /Library/Keychains/System.keychain; do
  security find-certificate -a -p "$kc" >> "$OUT" 2>/dev/null || true
done
echo "$OUT  ($(grep -c 'BEGIN CERTIFICATE' "$OUT") certificates)"
echo "export SIGHTLINE_CA_BUNDLE=$OUT"
