$results = @()
$featureDirs = Get-ChildItem D:\appforge-main\src\features -Directory -ErrorAction SilentlyContinue
foreach ($dir in $featureDirs) {
    $files = Get-ChildItem $dir.FullName -Recurse -Include "*.ts","*.tsx" -ErrorAction SilentlyContinue
    foreach ($file in $files) {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        if ($content -match "invalidateQueries") {
            $results += $file.FullName
        }
    }
}
$results | Out-File D:\openclaw\invalidate_features.txt
Write-Host "Found $($results.Count) files"
