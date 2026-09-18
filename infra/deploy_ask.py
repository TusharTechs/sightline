#!/usr/bin/env python3
"""
Deploy the hosted question endpoint.

Sightline can be interrupted with a question mid-scene, and until now that
only worked against a local service — which meant the people it was built for
could not reach it. The public demo is static files on GitHub Pages, and a
static page cannot hold an API key.

This puts the answering behind a Lambda function URL. One file, no
dependencies to package: the model is called over plain HTTPS and boto3 for
Polly is already in the runtime.

**This script never touches the model API key.** The function is deployed
without it and refuses to answer until the account owner sets it themselves,
so the key never passes through this script, a shell history or a log. See
the instructions it prints.

    python infra/deploy_ask.py
"""
import io
import json
import os
import time
import zipfile

ca = os.path.expanduser("~/.config/sightline-ca.pem")
if os.path.exists(ca):
    for v in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"):
        os.environ[v] = ca

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"          # the generative Polly voices are here
FN = "sightline-ask"
ROLE = "sightline-ask-role"
HERE = os.path.dirname(os.path.abspath(__file__))

iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)

trust = {"Version": "2012-10-17", "Statement": [{
    "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"}]}

try:
    role_arn = iam.create_role(
        RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
        Description="Sightline question endpoint")["Role"]["Arn"]
    print("  role created")
except ClientError as e:
    if e.response["Error"]["Code"] != "EntityAlreadyExists":
        raise
    role_arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    print("  role exists")

for arn in ("arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            "arn:aws:iam::aws:policy/AmazonPollyReadOnlyAccess"):
    iam.attach_role_policy(RoleName=ROLE, PolicyArn=arn)
print("  policies attached: logs, and Polly read-only")

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(HERE, "lambda_function.py"), "lambda_function.py")
code = buf.getvalue()
print(f"  package {len(code) / 1024:.1f} KB, no dependencies")

env_vars = {"SIGHTLINE_SITE": "https://tushartechs.github.io/sightline",
            "SIGHTLINE_MODEL": "claude-opus-5",
            "SIGHTLINE_VOICE": "Ruth"}

def create():
    """Retry through IAM propagation.

    A role is not immediately assumable by Lambda after it is created, and the
    failure is an InvalidParameterValueException reading "the role defined for
    the function cannot be assumed", which sounds like a permissions mistake
    rather than a few seconds of eventual consistency.
    """
    for attempt in range(12):
        try:
            lam.create_function(
                FunctionName=FN, Runtime="python3.12", Role=role_arn,
                Handler="lambda_function.lambda_handler",
                Code={"ZipFile": code}, Timeout=90, MemorySize=512,
                Environment={"Variables": env_vars}, Architectures=["arm64"])
            return
        except ClientError as err:
            msg = err.response["Error"]["Message"]
            if "cannot be assumed" not in msg or attempt == 11:
                raise
            time.sleep(5)


try:
    create()
    print("  function created")
except ClientError as e:
    if e.response["Error"]["Code"] != "ResourceConflictException":
        raise
    lam.update_function_code(FunctionName=FN, ZipFile=code)
    lam.get_waiter("function_updated").wait(FunctionName=FN)
    # Merge rather than replace, so a key set out of band survives a redeploy.
    existing = lam.get_function_configuration(FunctionName=FN) \
                  .get("Environment", {}).get("Variables", {})
    merged = dict(existing)
    merged.update(env_vars)
    lam.update_function_configuration(
        FunctionName=FN, Timeout=90, MemorySize=512,
        Environment={"Variables": merged})
    print("  function updated (existing env preserved)")

lam.get_waiter("function_updated").wait(FunctionName=FN)

try:
    url = lam.create_function_url_config(
        FunctionName=FN, AuthType="NONE",
        # "OPTIONS" is rejected: members are capped at six characters. The
        # function URL answers preflight itself, so POST is all that is needed.
        Cors={"AllowOrigins": ["*"], "AllowMethods": ["POST"],
              "AllowHeaders": ["content-type"], "MaxAge": 3600})
    print("  function URL created")
except ClientError as e:
    if e.response["Error"]["Code"] != "ResourceConflictException":
        raise
    url = lam.get_function_url_config(FunctionName=FN)
    print("  function URL exists")

try:
    lam.add_permission(FunctionName=FN, StatementId="public-invoke",
                       Action="lambda:InvokeFunctionUrl", Principal="*",
                       FunctionUrlAuthType="NONE")
    print("  public invoke permitted")
except ClientError as e:
    if e.response["Error"]["Code"] != "ResourceConflictException":
        raise
    print("  invoke permission already set")

has_key = "ANTHROPIC_API_KEY" in lam.get_function_configuration(FunctionName=FN) \
    .get("Environment", {}).get("Variables", {})

print("\nENDPOINT " + url["FunctionUrl"])
if not has_key:
    print("""
The model key is NOT set, and the endpoint will refuse to answer until it is.
Set it yourself so it never passes through this script:

  aws lambda update-function-configuration \\
    --function-name sightline-ask --region us-east-1 \\
    --environment "Variables={SIGHTLINE_SITE=https://tushartechs.github.io/sightline,\\
SIGHTLINE_MODEL=claude-opus-5,SIGHTLINE_VOICE=Ruth,ANTHROPIC_API_KEY=YOUR_KEY}"

or paste it into Configuration -> Environment variables in the Lambda console.""")
else:
    print("  model key: already set")
