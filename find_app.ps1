# Find the app ID file
Get-ChildItem -Path "D:\appforge-main" -Recurse -Filter "*.jsonc" -ErrorAction SilentlyContinue | ForEach-Object {
    $content = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
    if ($content -match "69741d9301465d2bac03e8bb") {
        Write-Output $_.FullName
    }
}
