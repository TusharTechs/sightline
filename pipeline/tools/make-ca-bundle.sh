#!/bin/bash
# Builds a certificate bundle from the machine's own trust store.
# Some networks require this for HTTPS clients to validate correctly. Run it if
# you see certificate errors from the AWS CLI or pip; skip it otherwise.
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
