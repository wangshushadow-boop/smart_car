# 编译和打包并部署到上位机的脚本
# Package and upload robot_host and ros_middleware.
[CmdletBinding()]
param(
  [string]$HostAddress = "192.168.3.85",
  [string]$UserName = "ubuntu",
  [string]$RemoteWorkspace = "/home/ubuntu/smart_car",
  [int]$SshPort = 22
)

$ErrorActionPreference = "Stop"

$robotHostRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $robotHostRoot
$archiveName = "small_car_host_$([guid]::NewGuid().ToString('N')).tar.gz"
$archivePath = Join-Path $env:TEMP $archiveName
$remoteArchive = "/tmp/$archiveName"
$remoteTarget = "${UserName}@${HostAddress}"
$remoteRobotHost = "$RemoteWorkspace/robot_host"
$remoteMiddleware = "$RemoteWorkspace/ros_middleware"
$remoteFirmware = "$RemoteWorkspace/small_car_f407"
$remoteCompose = "$remoteMiddleware/docker/compose.yaml"

try {
  Write-Host "[1/4] Package robot_host, ros_middleware, and MCU OTA files..."
  Push-Location $workspaceRoot
  try {
    $tarArgs = @(
      "-czf", $archivePath,
      "--exclude=robot_host/build*",
      "--exclude=robot_host/install*",
      "--exclude=robot_host/log*",
      "--exclude=robot_host/runtime",
      "robot_host",
      "ros_middleware",
      "small_car_f407/scripts"
    )
    $releaseFirmware = "small_car_f407/build/Release/small_car_f407.bin"
    if (Test-Path -LiteralPath $releaseFirmware) {
      $tarArgs += $releaseFirmware
    } else {
      Write-Warning "Release MCU firmware not found; OTA tool will be uploaded without a firmware image."
    }
    $releaseBootloader = "small_car_f407/build/Release/small_car_bootloader.bin"
    if (Test-Path -LiteralPath $releaseBootloader) {
      $tarArgs += $releaseBootloader
    } else {
      Write-Warning "Release MCU bootloader not found; first-time ST-Link flash will be required to populate 0x08000000."
    }
    & tar @tarArgs
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed" }
  } finally {
    Pop-Location
  }

  Write-Host "[2/4] Upload sources to ${remoteTarget}..."
  & scp -P $SshPort $archivePath "${remoteTarget}:${remoteArchive}"
  if ($LASTEXITCODE -ne 0) { throw "Upload failed" }

  Write-Host "[3/4] Build, test, and start on the host..."
  $remoteSteps = @(
    "set -e",
    "command -v cmake >/dev/null",
    "command -v docker >/dev/null",
    "docker compose version >/dev/null",
    "test -e /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C2C059301-if00",
    "test -e /dev/snd",
    "test -e /dev/video0",
    "if [ -f '$remoteCompose' ]; then docker compose -f '$remoteCompose' down --remove-orphans --timeout 15; fi",
    "mkdir -p '$remoteRobotHost' '$remoteMiddleware' '$remoteFirmware'",
    "rm -rf '$remoteRobotHost/core' '$remoteRobotHost/ros' '$remoteRobotHost/docs' '$remoteRobotHost/scripts' '$remoteRobotHost/tools' '$remoteRobotHost/systemd'",
    "rm -rf '$remoteMiddleware/src' '$remoteMiddleware/config' '$remoteMiddleware/docker' '$remoteMiddleware/docs'",
    "rm -rf '$remoteFirmware/scripts'",
    "tar -xzf '$remoteArchive' -C '$RemoteWorkspace'",
    "rm -f '$remoteArchive'",
    "if docker image inspect small-car-ros2:kilted >/dev/null 2>&1; then docker run --rm -v '${remoteRobotHost}:/target' small-car-ros2:kilted bash -lc 'rm -rf /target/build-ros /target/install-ros /target/log-ros'; else rm -rf '$remoteRobotHost/build-ros' '$remoteRobotHost/install-ros' '$remoteRobotHost/log-ros'; fi",
    "cmake -S '$remoteRobotHost' -B '$remoteRobotHost/build-host'",
    "cmake --build '$remoteRobotHost/build-host' -j4",
    "ctest --test-dir '$remoteRobotHost/build-host' --output-on-failure",
    "chmod +x '$remoteRobotHost/tools/recover_mcu_usb.sh' '$remoteRobotHost/scripts/verify_ros_runtime.sh' '$remoteFirmware/scripts/mcu_ota.py' '$remoteFirmware/scripts/update_mcu_firmware.sh'",
    "docker compose -f '$remoteCompose' up --build -d --force-recreate",
    "docker compose -f '$remoteCompose' ps",
    "attempt=1; while [ `$attempt -le 60 ]; do if docker compose -f '$remoteCompose' exec -T small_car_ros2 bash /workspace/smart_car/robot_host/scripts/verify_ros_runtime.sh; then exit 0; fi; attempt=`$((attempt + 1)); sleep 2; done; echo 'ROS health check failed' >&2; docker compose -f '$remoteCompose' ps; docker compose -f '$remoteCompose' logs --tail=250; exit 1"
  )
  & ssh -p $SshPort $remoteTarget ($remoteSteps -join " && ")
  if ($LASTEXITCODE -ne 0) { throw "Host deployment failed" }

  Write-Host "[4/4] Deployment complete: $RemoteWorkspace"
} finally {
  if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
  }
}
