# Find files that likely have React Query issues
# Look for patterns like invalidateQueries([

$srcPath = "D:\appforge-main\src"
$files = Get-ChildItem $srcPath -Recurse -File | Where-Object { $_.Extension -in @('.ts','.tsx','.js','.jsx') -and $_.FullName -notlike "*node_modules*" }

$found = @()
$count = 0
foreach ($file in $files) {
    $count++
    if ($count % 100 -eq 0) { Write-Host "Checked $count files..." }
    try {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        if ($content -match "invalidateQueries\s*\(\s*\[") {
            Write-Host "FOUND: $($file.FullName)"
            $found += $file.FullName
        }
    } catch {}
}

$found | Out-File "D:\openclaw\invalidate_queries_found.txt"
Write-Host "Found $($found.Count) files with old invalidateQueries syntax"
