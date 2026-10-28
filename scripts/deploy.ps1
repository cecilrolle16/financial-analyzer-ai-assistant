# Deploy only after the AWS change is approved.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

sam build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

sam deploy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$account = aws sts get-caller-identity --query Account --output text
aws s3 sync frontend "s3://financial-analyzer-site-$account-us-east-1" --delete
