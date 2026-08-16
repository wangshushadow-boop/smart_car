$ErrorActionPreference = "Stop"

$envRoot = $PSScriptRoot
$toolsRoot = Join-Path $envRoot "tools"
$archivesRoot = Join-Path $envRoot "archives"
$armRoot = Join-Path $toolsRoot "arm-gnu"
$cmakeRoot = Join-Path $toolsRoot "cmake"
$ninjaRoot = Join-Path $toolsRoot "ninja"

function Expand-ToolArchive {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Archive,
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedFile,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedHash
  )

  if (Test-Path -LiteralPath $ExpectedFile) {
    return
  }

  if (-not (Test-Path -LiteralPath $Archive)) {
    throw "Missing build environment archive: $Archive. Run 'git lfs pull'."
  }

  $actualHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
  if ($actualHash -ne $ExpectedHash) {
    throw "Build environment archive checksum mismatch: $Archive"
  }

  Write-Host "Extracting $(Split-Path -Leaf $Archive)..."
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
}

Expand-ToolArchive `
  -Archive (Join-Path $archivesRoot "arm-gnu-toolchain-14.3.rel1.zip") `
  -Destination $armRoot `
  -ExpectedFile (Join-Path $armRoot "bin\arm-none-eabi-gcc.exe") `
  -ExpectedHash "864C0C8815857D68A1BBBA2E5E2782255BB922845C71C97636004A3D74F60986"
Expand-ToolArchive `
  -Archive (Join-Path $archivesRoot "cmake-4.3.3-windows-x86_64.zip") `
  -Destination $cmakeRoot `
  -ExpectedFile (Join-Path $cmakeRoot "cmake-4.3.3-windows-x86_64\bin\cmake.exe") `
  -ExpectedHash "935ADE9E5E8723583C07F44C5592CEA2A1C8F65C56CA7E07B34C025C880E0BD6"
Expand-ToolArchive `
  -Archive (Join-Path $archivesRoot "ninja-1.13.2-win.zip") `
  -Destination $ninjaRoot `
  -ExpectedFile (Join-Path $ninjaRoot "ninja.exe") `
  -ExpectedHash "07FC8261B42B20E71D1720B39068C2E14FFCEE6396B76FB7A795FB460B78DC65"

$toolPaths = @(
  (Join-Path $cmakeRoot "cmake-4.3.3-windows-x86_64\bin"),
  $ninjaRoot,
  (Join-Path $armRoot "bin")
)
$env:Path = ($toolPaths -join [IO.Path]::PathSeparator) +
  [IO.Path]::PathSeparator + $env:Path

Write-Host "STM32 build environment is ready:"
cmake --version | Select-Object -First 1
ninja --version
arm-none-eabi-gcc --version | Select-Object -First 1
