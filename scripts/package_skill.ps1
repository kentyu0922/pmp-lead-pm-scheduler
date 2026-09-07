# scripts/package_skill.ps1 - Windows PowerShell Native Packager
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseDir = Split-Path -Parent $scriptDir
$rootFolderName = "pmp-lead-pm-scheduler"
$distDir = Join-Path $baseDir "dist"
$zipName = "pmp-lead-pm-scheduler.zip"
$outZip = Join-Path $distDir $zipName

Write-Host "[package_skill] Pre-packaging cleanup..." -ForegroundColor Cyan
& (Join-Path $scriptDir "clean_dist.ps1")

if (!(Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
}
if (Test-Path $outZip) {
    Remove-Item -Force $outZip
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipArchive = [System.IO.Compression.ZipFile]::Open($outZip, [System.IO.Compression.ZipArchiveMode]::Create)

$excludeDirs = @("__pycache__", ".venv", "venv", "env", ".git", ".vscode", ".idea", "dist", "build", "scratch")
$excludeExts = @(".pyc", ".pyo", ".log", ".tmp")

$files = Get-ChildItem -Path $baseDir -Recurse -File

$count = 0
foreach ($file in $files) {
    $relPath = $file.FullName.Substring($baseDir.Length + 1)
    $parts = $relPath.Split([System.IO.Path]::DirectorySeparatorChar)
    
    $skip = $false
    foreach ($p in $parts) {
        if ($excludeDirs -contains $p) {
            $skip = $true
            break
        }
    }
    if ($skip) { continue }
    
    if ($excludeExts -contains $file.Extension) { continue }
    
    if ($parts[0] -eq "output_mpp" -and $parts.Length -gt 1) {
        if ($parts[1] -ne ".gitkeep" -and $parts[1] -ne "README.md") {
            continue
        }
    }
    
    $entryName = ($rootFolderName + "/" + $relPath.Replace("\", "/"))
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zipArchive, $file.FullName, $entryName, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    $count++
}

$zipArchive.Dispose()

$size = (Get-Item $outZip).Length
$sizeKB = [math]::Round($size / 1024, 1)
Write-Host "[package_skill] Archive created: $outZip ($count files, $sizeKB KB)" -ForegroundColor Green

# Also sync to Desktop
$desktopZip = "C:\Users\HUAWEI\Desktop\$zipName"
try {
    Copy-Item -Path $outZip -Destination $desktopZip -Force
    Write-Host "[package_skill] Synced to Desktop: $desktopZip" -ForegroundColor Green
} catch {
    Write-Host "[package_skill] Notice: could not overwrite desktop file: $_" -ForegroundColor Yellow
}
