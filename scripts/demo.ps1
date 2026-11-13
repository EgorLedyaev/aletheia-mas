# Windows demo runner. Equivalent of `make demo`.
param([string]$Py = "python", [switch]$Offline)
if ($Offline) { $env:ALETHEIA_OFFLINE = "1" }
& $Py -m aletheia.cli scenarios --run
