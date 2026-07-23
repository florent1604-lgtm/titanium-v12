param([switch]$OpenBrowser, [switch]$NoWatch)

# Compatibilite : le point d'entree canonique est gitnexus_session.ps1.
$Session = Join-Path $PSScriptRoot "gitnexus_session.ps1"
& $Session -OpenBrowser:$OpenBrowser -NoWatch:$NoWatch
exit $LASTEXITCODE
