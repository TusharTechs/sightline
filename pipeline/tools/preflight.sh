#!/bin/bash
# Verifies everything stage 2+3 needs, without spending a model call on failure.
CA="${SIGHTLINE_CA_BUNDLE:-$HOME/.config/sightline-ca.pem}"
[ -f "$CA" ] && export AWS_CA_BUNDLE="$CA" SSL_CERT_FILE="$CA" REQUESTS_CA_BUNDLE="$CA" \
  && echo "CA bundle     OK  ($CA)" || echo "CA bundle     MISSING — run tools/make-ca-bundle.sh"
[ -n "${SIGHTLINE_AWS_PROFILE:-}" ] && export AWS_PROFILE="$SIGHTLINE_AWS_PROFILE"
echo "AWS profile   ${AWS_PROFILE:-<default>}"
aws sts get-caller-identity >/dev/null 2>&1 \
  && echo "credentials   OK" || echo "credentials   FAILED"
echo -n "bedrock model access  "
aws bedrock-runtime invoke-model --region "${AWS_REGION:-us-east-1}" \
  --model-id "${SIGHTLINE_MODEL:-anthropic.claude-opus-5}" \
  --body "$(printf '{"anthropic_version":"bedrock-2023-05-31","max_tokens":8,"messages":[{"role":"user","content":"hi"}]}' | base64)" \
  /dev/null >/dev/null 2>/tmp/.pf && echo "OK" || { echo "FAILED"; sed -E 's/^/              /' /tmp/.pf | tail -2; }
