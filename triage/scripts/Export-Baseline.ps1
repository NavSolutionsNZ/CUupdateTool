<#
.SYNOPSIS
    Export all application objects from a NAV/BC database, split into one file
    per object, and rename to the triage tool's <Prefix>-<TypeChar><Id>.txt
    convention (e.g. CU-T18.txt, OB-T18.txt).

.DESCRIPTION
    Called by the CU Triage tool (or run by hand). Windows authentication only:
    the account running PowerShell must have SQL access to the database. No
    credentials are taken or stored.

    Flow:
      1. Import the NAV model-tools module.
      2. Export-NAVApplicationObject -> one combined text file (all types, the
         object-id range below the incadea dev-license ceiling, so system /
         platform objects are skipped).
      3. Split-NAVApplicationObjectFile -PreserveFormatting -> one file per
         object (native names like TAB18.TXT / COD80.TXT).
      4. Rename each to <Prefix>-<TypeChar><Id>.txt using the first letter of
         the 3-letter type code (TAB->T, COD->C, PAG->P, REP->R, XML->X, ...),
         matching the convention the triage / CUupdate tools key on.
      5. Remove the temp combined file.

    Exits non-zero on any failure so the calling tool can detect it.

.PARAMETER DatabaseServer
    SQL server hosting the database, e.g. 10.24.244.19

.PARAMETER DatabaseName
    Database to export, e.g. iDealer_2026Q1_DB

.PARAMETER OutFolder
    Destination folder for the per-object files. Created if missing.

.PARAMETER Prefix
    Filename prefix, e.g. OB (old baseline) or CU (new baseline).

.PARAMETER Filter
    Object filter. Default 'Id=1..99008535' -- all objects up to the incadea
    dev-license ceiling, excluding system/platform objects above it.

.PARAMETER ModulePath
    Path to Microsoft.Dynamics.Nav.Model.Tools.psd1. Defaults to the BC140
    RoleTailored Client location.

.PARAMETER WorkFile
    Temp combined-export path. Defaults to a file in the system temp folder.

.EXAMPLE
    .\Export-Baseline.ps1 -DatabaseServer 10.24.244.19 `
        -DatabaseName iDealer_2026Q1_DB -OutFolder C:\triage\existing -Prefix OB
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $DatabaseServer,
    [Parameter(Mandatory = $true)] [string] $DatabaseName,
    [Parameter(Mandatory = $true)] [string] $OutFolder,
    [Parameter(Mandatory = $true)] [string] $Prefix,
    # NavServer params are accepted (so callers can pass them uniformly) but are
    # NOT used by Export-NAVApplicationObject, which has no such parameters. They
    # are reserved for the Import/Compile steps, which do accept them.
    [string] $NavServerName = '',
    [string] $NavServerInstance = '',
    [int]    $NavServerManagementPort = 0,
    [string] $Filter = 'Id=1..99008535',
    [switch] $Append,
    [string] $ModulePath = 'C:\Program Files (x86)\Microsoft Dynamics 365 Business Central\140\RoleTailored Client\Microsoft.Dynamics.Nav.Model.Tools.psd1',
    [string] $WorkFile = ''
)

$ErrorActionPreference = 'Stop'
# The "registered with several NAV Server instances" prompt is interactive by
# default. Suppress all confirmation so the export runs unattended; -Force on the
# cmdlet plus ConfirmPreference=None answers it automatically.
$ConfirmPreference = 'None'

try {
    # 1. Import the model-tools module.
    if (!(Test-Path $ModulePath)) {
        throw "Model-tools module not found at: $ModulePath"
    }
    Import-Module $ModulePath -Force

    # Temp combined-export file.
    if ([string]::IsNullOrWhiteSpace($WorkFile)) {
        $WorkFile = Join-Path $env:TEMP ("baseline_{0}_{1}.txt" -f $Prefix, [System.Guid]::NewGuid().ToString('N'))
    }

    # Ensure destination exists. Clear stale per-object files for this prefix on
    # the FIRST call (a re-run must not leave deleted objects behind); subsequent
    # per-type calls use -Append so they accumulate into the same folder.
    if (!(Test-Path $OutFolder)) {
        New-Item -ItemType Directory -Path $OutFolder -Force | Out-Null
    } elseif (-not $Append) {
        Get-ChildItem -Path $OutFolder -Filter ("{0}-*.txt" -f $Prefix) -File -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }

    # 2. Export all objects (combined) below the license ceiling.
    # NOTE: Export-NAVApplicationObject does NOT accept NavServerName /
    # NavServerInstance / NavServerManagementPort -- those exist only on Import /
    # Compile / Delete. Export identifies the DB by SQL server + database. The
    # "registered with several NAV Server instances" prompt is suppressed by
    # -Force; -ExportTxtSkipUnlicensed avoids licence stops on vendor objects.
    Write-Host ("Exporting {0} from {1} (filter: {2}) ..." -f `
        $DatabaseName, $DatabaseServer, $Filter)

    Export-NAVApplicationObject `
        -DatabaseServer $DatabaseServer `
        -DatabaseName   $DatabaseName `
        -Path           $WorkFile `
        -Filter         $Filter `
        -ExportTxtSkipUnlicensed `
        -Force | Out-Null

    if (!(Test-Path $WorkFile)) {
        throw "Export produced no file: $WorkFile"
    }

    # 3 + 4. Split (preserve formatting) and rename to <Prefix>-<TypeChar><Id>.txt
    $count = 0
    Split-NAVApplicationObjectFile -Source $WorkFile -Destination $OutFolder -PreserveFormatting -Force -PassThru |
        ForEach-Object {
            $DefaultName = $_.Name      # e.g. "TAB18.TXT"
            if ($DefaultName -match "^([A-Za-z]+)(\d+)\.[Tt][Xx][Tt]$") {
                $RawType     = $Matches[1]
                $ObjID       = $Matches[2]
                $ObjTypeChar = $RawType.Substring(0, 1).ToUpper()
                $NewFileName = "${Prefix}-${ObjTypeChar}${ObjID}.txt"
                if ($DefaultName -ne $NewFileName) {
                    Rename-Item -Path $_.FullName -NewName $NewFileName -Force
                }
                $count++
            }
        }

    # 5. Clean up the temp combined file.
    Remove-Item -Path $WorkFile -Force -ErrorAction SilentlyContinue

    Write-Host ("Done: {0} object(s) -> {1} (prefix {2})" -f $count, $OutFolder, $Prefix) -ForegroundColor Green
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
