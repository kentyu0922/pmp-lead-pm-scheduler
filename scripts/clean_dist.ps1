# scripts/clean_dist.ps1 - Pre-packaging Sanitizer for Windows PowerShell
Write-Host "[clean_dist] Cleaning __pycache__ directories..." -ForegroundColor Cyan
Get-ChildItem -Path . -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

Write-Host "[clean_dist] Cleaning *.pyc, *.pyo, and *.log files..." -ForegroundColor Cyan
Get-ChildItem -Path . -Include "*.pyc", "*.pyo", "*.log" -Recurse -File -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host "[clean_dist] Cleaning output_mpp/ test artifacts..." -ForegroundColor Cyan
Get-ChildItem -Path "output_mpp" -Exclude ".gitkeep", "README.md" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

Write-Host "[clean_dist] Sanitization complete! Distribution directory is clean." -ForegroundColor Green
