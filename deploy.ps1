# Deploys the committed code (git HEAD) to the VPS and rebuilds the container.
# Uses the "receipts-vps" host alias from ~/.ssh/config (key login, no password).
# Secrets: only .env is copied, over scp; it is never in git or in the image.
param(
    [string]$Target = "receipts-vps",
    [string]$RemoteDir = "/opt/receipts"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$archive = Join-Path $env:TEMP "receipts-deploy.tar.gz"
git archive --format=tar.gz -o $archive HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }

ssh -o BatchMode=yes $Target "mkdir -p $RemoteDir"
if ($LASTEXITCODE -ne 0) { throw "ssh failed" }
scp -q $archive .env "${Target}:$RemoteDir/"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

$remote = "cd $RemoteDir && tar xzf receipts-deploy.tar.gz && rm receipts-deploy.tar.gz && sed -i 's/\r`$//' .env && chmod 600 .env && " +
          "docker compose up -d --build --quiet-pull 2>&1 | tail -15 && sleep 4 && docker compose ps && " +
          "docker compose exec -T api python -c 'import urllib.request as u; print(u.urlopen(\`"http://localhost:8000/health\`").read().decode())'"
ssh -o BatchMode=yes $Target $remote
if ($LASTEXITCODE -ne 0) { throw "remote deploy failed" }
Remove-Item $archive -Confirm:$false
