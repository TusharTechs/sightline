#!/bin/bash
# Verifies everything stage 2+3 needs, before spending a model call.
CA="${SIGHTLINE_CA_BUNDLE:-$HOME/.config/sightline-ca.pem}"
if [ -f "$CA" ]; then
  export AWS_CA_BUNDLE="$CA" SSL_CERT_FILE="$CA" REQUESTS_CA_BUNDLE="$CA"
  echo "CA bundle      OK   ($CA)"
else
  echo "CA bundle      MISSING — run tools/make-ca-bundle.sh"
fi

WANT="${SIGHTLINE_AWS_PROFILE:-}"
if [ -n "$WANT" ]; then
  if aws configure list-profiles 2>/dev/null | grep -qx "$WANT"; then
    export AWS_PROFILE="$WANT"
    echo "AWS profile    OK   ($WANT)"
  else
    echo "AWS profile    MISSING — no profile named '$WANT'."
    echo "                    create it:  aws configure --profile $WANT"
    echo "                    existing:   $(aws configure list-profiles 2>/dev/null | tr '\n' ' ')"
    exit 1
  fi
else
  echo "AWS profile    <default>  — set SIGHTLINE_AWS_PROFILE to keep hackathon"
  echo "                           credentials separate from anything else here"
fi

if aws sts get-caller-identity >/dev/null 2>&1; then
  ACCT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
  echo "credentials    OK   (account ...${ACCT: -4} — confirm this is the hackathon one)"
else
  echo "credentials    FAILED"; exit 1
fi

REGION="${AWS_REGION:-us-east-1}"
printf "model access   "
BODY=$(printf '{"anthropic_version":"bedrock-2023-05-31","max_tokens":8,"messages":[{"role":"user","content":"hi"}]}' | base64)
if aws bedrock-runtime invoke-model --region "$REGION" \
     --model-id "${SIGHTLINE_MODEL:-anthropic.claude-opus-5}" \
     --body "$BODY" /dev/null >/dev/null 2>/tmp/.pf; then
  echo "OK   ($REGION)"; echo; echo "Ready. Run the salience stage."
else
  echo "FAILED ($REGION)"
  sed -E 's/^/               /' /tmp/.pf | tail -2
  case "$(cat /tmp/.pf)" in
    *"Error 002"*)
      echo
      echo "  'Error 002' is an ACCOUNT-level gate, not the per-model toggle."
      echo "  Enabling model access in the console does not clear it. Either the"
      echo "  credentials belong to a different account than the one you enabled,"
      echo "  or the account is under an Organization policy denying Bedrock."
      echo "  Use the hackathon account via its own profile." ;;
  esac
  exit 1
fi
