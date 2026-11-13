# Windows one-command setup (PowerShell). Equivalent of `make setup`.
param([string]$Py = "python")
& $Py -m pip install -e .
if ($LASTEXITCODE -ne 0) { exit 1 }
& $Py scripts/fetch_vina.py
& $Py scripts/verify_registry.py
Write-Host "setup complete -- run: .\scripts\demo.ps1"
