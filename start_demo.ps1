# Starts the local demo environment (portable PostgreSQL + Odoo 18) built in _runtime/.
# Usage:  .\start_demo.ps1                -> sales-only demo        http://localhost:8069 (admin / admin)
#         .\start_demo.ps1 -Inventory     -> demo with the Inventory app (kegs scanned on delivery orders)
#         .\start_demo.ps1 -Reset         -> rebuild the chosen demo database from scratch first
#         .\start_demo.ps1 -Test          -> run both test suites on throw-away databases
param([switch]$Inventory, [switch]$Reset, [switch]$Test)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$rt = Join-Path $PSScriptRoot '_runtime'
$py = Join-Path $rt 'venv\Scripts\python.exe'
$odoo = Join-Path $rt 'odoo\odoo-bin'
$conf = Join-Path $rt 'odoo.conf'
$pgbin = Join-Path $rt 'pgsql\bin'

function Invoke-Odoo([string[]]$OdooArgs) {
    & $py $odoo -c $conf @OdooArgs
    if ($LASTEXITCODE -ne 0) { throw "odoo-bin exited with code $LASTEXITCODE" }
}

& "$pgbin\pg_ctl.exe" -D "$rt\pgdata" status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Starting PostgreSQL on port 5433...'
    Start-Process -WindowStyle Hidden -FilePath "$pgbin\pg_ctl.exe" -ArgumentList @('-D', "$rt\pgdata", '-l', "$rt\pg.log", 'start')
    Start-Sleep -Seconds 4
}

if ($Test) {
    foreach ($db in 'keg_test', 'keg_test_stock') { & "$pgbin\dropdb.exe" -p 5433 -U odoo --if-exists $db }
    Write-Host '--- keg_tracking (sales-only flow) ---'
    Invoke-Odoo @('-d', 'keg_test', '-i', 'keg_tracking', '--test-tags', '/keg_tracking', '--stop-after-init', '--log-level=test')
    Write-Host '--- keg_tracking_stock (Inventory flow) ---'
    Invoke-Odoo @('-d', 'keg_test_stock', '-i', 'keg_tracking_stock', '--test-tags', '/keg_tracking_stock', '--stop-after-init', '--log-level=test')
    exit 0
}

$db = if ($Inventory) { 'keg_demo_stock' } else { 'keg_demo' }

if ($Reset) {
    & "$pgbin\dropdb.exe" -p 5433 -U odoo --if-exists $db
    Remove-Item -Recurse -Force "$rt\filestore\filestore\$db" -ErrorAction SilentlyContinue
}

& "$pgbin\psql.exe" -p 5433 -U odoo -d $db -tAc 'select 1' *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating the $db database with demo data (a few minutes)..."
    if ($Inventory) {
        # Inventory first, as in a brewery already using it; keg_tracking_stock then installs automatically.
        Invoke-Odoo @('-d', $db, '-i', 'sale_stock', '--stop-after-init', '--log-level=warn')
    }
    Invoke-Odoo @('-d', $db, '-i', 'keg_tracking', '--stop-after-init', '--log-level=warn')
}

Write-Host "Odoo running on http://localhost:8069  (database $db, login admin / admin) - Ctrl+C to stop"
& $py $odoo -c $conf -d $db --db-filter="^$db`$"
