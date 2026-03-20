$files = Get-ChildItem D:\appforge-main\src -Recurse -Include "*.ts","*.tsx" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*node_modules*" } | ForEach-Object { $content = Get-Content $_.FullName -Raw; if ($content -match "invalidateQueries") { $_.FullName } }
$files | Out-File D:\openclaw\invalidate_files.txt
Write-Host "Found $($files.Count) files"
