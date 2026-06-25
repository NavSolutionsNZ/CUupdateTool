<#
.SYNOPSIS
    Join every object file in the import folder into one combined file, then
    import that file into the customer database (overwrite, no schema sync,
    no compile).

.DESCRIPTION
    The final pipeline step. Takes the Import/ folder the tool has already
    assembled (new + take-straight vendor objects + auto-merged outputs) and:

      1. Imports the NAV model-tools module.
      2. Joins every *.txt in the import folder into a single combined file
         via Join-NAVApplicationObjectFile (whatever is present is imported --
         no filtering, so a still-incomplete set with manual objects missing
         imports the ready objects regardless).
      3. Imports the combined file into the SQL database with
         Import-NAVApplicationObject -ImportAction Overwrite
         -SynchronizeSchemaChanges No. Import only -- compile is left to the
         developer.

    Windows authentication only: the account running PowerShell must have SQL
    access to the database. No credentials are taken or stored.

    The target is identified by SQL server + database (not a NAV service-tier
    instance); ImportAction Overwrite + SynchronizeSchemaChanges No matches the
    proven manual import. Exits non-zero on any failure so the calling tool can
    detect it.

.PARAMETER ImportFolder
    Folder of per-object .txt files to join and import (the job root's Import/).

.PARAMETER DatabaseServer
    SQL server hosting the customer database, e.g. 10.24.244.19

.PARAMETER DatabaseName
    Customer database to import into, e.g. Webbline_Dev_DB

.PARAMETER JoinedFile
    Combined output path. Defaults to <ImportFolder>\joined\Combined.txt.

.PARAMETER ModulePath
    Path to Microsoft.Dynamics.Nav.Model.Tools.psd1. Defaults to the BC140
    RoleTailored Client location.

.EXAMPLE
    .\Join-And-Import.ps1 -ImportFolder C:\job\Import `
        -DatabaseServer 10.24.244.19 -DatabaseName Webbline_Dev_DB
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $ImportFolder,
    [Parameter(Mandatory = $true)] [string] $DatabaseServer,
    [Parameter(Mandatory = $true)] [string] $DatabaseName,
    [string] $JoinedFile = '',
    [string] $ModulePath = 'C:\Program Files (x86)\Microsoft Dynamics 365 Business Central\140\RoleTailored Client\Microsoft.Dynamics.Nav.Model.Tools.psd1'
)

$ErrorActionPreference = 'Stop'
# Suppress the interactive "registered with several NAV Server instances" /
# overwrite confirmations so the import runs unattended.
$ConfirmPreference = 'None'

try {
    # 1. Import the model-tools module.
    if (!(Test-Path $ModulePath)) {
        throw "Model-tools module not found at: $ModulePath"
    }
    Import-Module $ModulePath -Force

    if (!(Test-Path -LiteralPath $ImportFolder)) {
        throw "Import folder not found: $ImportFolder"
    }

    # Default the joined file to <ImportFolder>\joined\Combined.txt.
    if ([string]::IsNullOrWhiteSpace($JoinedFile)) {
        $JoinedFile = Join-Path (Join-Path $ImportFolder 'joined') 'Combined.txt'
    }
    $joinedFolder = Split-Path -Parent $JoinedFile
    if (-not (Test-Path -LiteralPath $joinedFolder)) {
        New-Item -ItemType Directory -Path $joinedFolder -Force | Out-Null
    }

    # Guard: nothing to import is a hard failure, not a silent success.
    $srcFiles = @(Get-ChildItem -Path (Join-Path $ImportFolder '*.txt') -File -ErrorAction SilentlyContinue)
    if ($srcFiles.Count -eq 0) {
        throw "No .txt object files found in: $ImportFolder"
    }

    # 2. Join every object file into the single combined file.
    Write-Host ("Joining {0} object file(s) -> {1} ..." -f $srcFiles.Count, $JoinedFile)
    Join-NAVApplicationObjectFile `
        -Source (Join-Path $ImportFolder '*.txt') `
        -Destination $JoinedFile `
        -Force

    if (!(Test-Path -LiteralPath $JoinedFile)) {
        throw "Join produced no file: $JoinedFile"
    }

    # 3. Import the combined file (overwrite, no schema sync, import only).
    # NB: Import-NAVApplicationObject in BC140 does NOT accept -Force (only
    # Join-NAVApplicationObjectFile does). Confirmation is suppressed via
    # -Confirm:$false and $ConfirmPreference='None'.
    Write-Host ("Importing {0} into {1} on {2} (Overwrite, no schema sync) ..." -f `
        $JoinedFile, $DatabaseName, $DatabaseServer)
    Import-NAVApplicationObject `
        -Path $JoinedFile `
        -DatabaseServer $DatabaseServer `
        -DatabaseName $DatabaseName `
        -ImportAction Overwrite `
        -SynchronizeSchemaChanges No `
        -Confirm:$false

    Write-Host ("Done: imported {0} object file(s) into {1}. Compile in the dev environment." -f `
        $srcFiles.Count, $DatabaseName) -ForegroundColor Green
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
