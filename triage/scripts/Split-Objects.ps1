<#
.SYNOPSIS
    Split an existing combined NAV object export into one file per object and
    rename to <Prefix>-<TypeChar><Id>.txt (e.g. CU-T18.txt).

.DESCRIPTION
    For an already-exported file (e.g. HQ's combined list of objects changed in
    the new CU) -- no database connection needed, just split + rename. Uses
    Rich's proven split logic with -PreserveFormatting so objects are byte-
    faithful for comparison.

.PARAMETER Source
    The combined export .txt to split.

.PARAMETER Destination
    Folder for the per-object files. Created if missing; existing
    <Prefix>-*.txt are cleared first so a re-run is clean.

.PARAMETER Prefix
    Filename prefix, e.g. CU.

.PARAMETER ModulePath
    Path to Microsoft.Dynamics.Nav.Model.Tools.psd1 (BC140 default).

.EXAMPLE
    .\Split-Objects.ps1 -Source C:\hq\NewCU.txt -Destination C:\job\hq -Prefix CU
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Source,
    [Parameter(Mandatory = $true)] [string] $Destination,
    [Parameter(Mandatory = $true)] [string] $Prefix,
    [string] $ModulePath = 'C:\Program Files (x86)\Microsoft Dynamics 365 Business Central\140\RoleTailored Client\Microsoft.Dynamics.Nav.Model.Tools.psd1'
)

$ErrorActionPreference = 'Stop'

try {
    if (!(Test-Path $ModulePath)) { throw "Model-tools module not found at: $ModulePath" }
    Import-Module $ModulePath -Force

    if (!(Test-Path $Source)) { throw "Source file not found: $Source" }

    if (!(Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    } else {
        Get-ChildItem -Path $Destination -Filter ("{0}-*.txt" -f $Prefix) -File -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }

    $count = 0
    Split-NAVApplicationObjectFile -Source $Source -Destination $Destination -PreserveFormatting -Force -PassThru |
        ForEach-Object {
            $DefaultName = $_.Name
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

    Write-Host ("Done: {0} object(s) -> {1} (prefix {2})" -f $count, $Destination, $Prefix) -ForegroundColor Green
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
