# Deploys the committed code (git HEAD) to the VPS and rebuilds the container.
# You type the VPS password when ssh/scp ask for it. Secrets: only .env is copied, over scp.
param(
    [string]$HostName = "179.67.199.150",
    [string]$User = "root",
    [string]$RemoteDir = "/opt/receipts"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$archive = Join-Path $env:TEMP "receipts-deploy.tar.gz"
git archive --format=tar.gz -o $archive HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }

$files = @($archive)
if (Test-Path .env) { $files += (Resolve-Path .env).Path } else { Write-Host "No local .env: the server keeps its own, or starts from .env.example." }

ssh "$User@$HostName" "mkdir -p $RemoteDir"
if ($LASTEXITCODE -ne 0) { throw "ssh failed" }
scp $files "${User}@${HostName}:$RemoteDir/"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

$remote = "cd $RemoteDir && tar xzf receipts-deploy.tar.gz && rm receipts-deploy.tar.gz && " +
          "( [ -f .env ] || cp .env.example .env ) && chmod 600 .env && " +
          "docker compose up -d --build && sleep 3 && docker compose ps && " +
          "curl -s http://localhost:`$(grep -E '^HOST_PORT=' .env | cut -d= -f2 || echo 80)/health"
ssh "$User@$HostName" $remote
Remove-Item $archive -Confirm:$false
