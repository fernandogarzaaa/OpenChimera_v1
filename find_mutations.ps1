$results = @()
$allFiles = Get-ChildItem D:\appforge-main\src -Recurse -Include "*.ts","*.tsx","*.js","*.jsx" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*node_modules*" }
foreach ($file in $allFiles) {
    $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
    if ($content -match "useMutation|useQuery") {
        $results += $file.FullName
    }
}
$results | Out-File D:\openclaw\mutation_files.txt
Write-Host "Found $($results.Count) files with useMutation/useQuery"
