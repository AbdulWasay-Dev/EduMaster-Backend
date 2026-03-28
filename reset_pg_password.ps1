# Run this script as Administrator (right-click PowerShell → "Run as Administrator")
# It temporarily sets trust auth, resets the postgres password to match .env, then restores.

$pgData = "C:\Program Files\PostgreSQL\18\data"
$pgBin  = "C:\Program Files\PostgreSQL\18\bin"
$newPassword = "Moosajutt786"

$hbaPath = "$pgData\pg_hba.conf"
$hbaBackup = "$pgData\pg_hba.conf.bak"

Write-Host "Backing up pg_hba.conf..."
Copy-Item $hbaPath $hbaBackup -Force

Write-Host "Enabling trust auth for localhost..."
(Get-Content $hbaPath) `
    -replace "^(host\s+all\s+all\s+127\.0\.0\.1/32\s+)scram-sha-256", '$1trust' `
    -replace "^(host\s+all\s+all\s+::1/128\s+)scram-sha-256",           '$1trust' |
    Set-Content $hbaPath

Write-Host "Restarting PostgreSQL..."
Restart-Service "postgresql-x64-18" -Force
Start-Sleep -Seconds 3

Write-Host "Resetting postgres password to '$newPassword'..."
$env:PGPASSWORD = ""
$sql = "ALTER USER postgres WITH PASSWORD '$newPassword';"
& "$pgBin\psql.exe" -U postgres -d postgres -c $sql

Write-Host "Restoring original pg_hba.conf..."
Copy-Item $hbaBackup $hbaPath -Force

Write-Host "Restarting PostgreSQL (final)..."
Restart-Service "postgresql-x64-18" -Force
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "Done! Testing connection..."
$env:PGPASSWORD = $newPassword
& "$pgBin\psql.exe" -U postgres -d postgres -c "SELECT version();" 2>&1
$env:PGPASSWORD = ""
