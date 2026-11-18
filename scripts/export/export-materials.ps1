param(
    [string]$Database,
    [string]$OutputDirectory,
    [string]$Java = 'java',
    [string]$MavenRepository = (Join-Path $env:USERPROFILE '.m2/repository')
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (!$Database) { $Database = Join-Path $projectRoot 'data/nan_novel.db' }
if (!$OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot ('data/exports/materials-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$null = New-Item -ItemType Directory -Force -Path (Split-Path $outputPath -Parent)

# Use the project's existing Maven dependencies; no downloads or service startup.
$coordinates = @(
    'org/xerial/sqlite-jdbc/3.46.1.3/sqlite-jdbc-3.46.1.3.jar',
    'org/slf4j/slf4j-api/2.0.13/slf4j-api-2.0.13.jar',
    'com/fasterxml/jackson/core/jackson-core/2.15.4/jackson-core-2.15.4.jar',
    'com/fasterxml/jackson/core/jackson-databind/2.15.4/jackson-databind-2.15.4.jar',
    'com/fasterxml/jackson/core/jackson-annotations/2.15.4/jackson-annotations-2.15.4.jar'
)
$jars = foreach ($coordinate in $coordinates) {
    $jar = Join-Path $MavenRepository $coordinate
    if (!(Test-Path -LiteralPath $jar -PathType Leaf)) { throw "Missing Maven dependency: $jar" }
    $jar
}
& $Java '-Dfile.encoding=UTF-8' '--class-path' ($jars -join [IO.Path]::PathSeparator) (Join-Path $PSScriptRoot 'ExportMaterials.java') $Database $outputPath
if ($LASTEXITCODE -ne 0) { throw "Export failed; do not use incomplete output: $outputPath" }
