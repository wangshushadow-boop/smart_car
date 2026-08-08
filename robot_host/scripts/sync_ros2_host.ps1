# 编译和打包并部署到上位机的脚本
# Package and upload robot_host and ros_middleware.
[CmdletBinding()]
param(
  [string]$HostAddress = "192.168.3.85",
  [string]$UserName = "ubuntu",
  [string]$RemoteWorkspace = "/home/ubuntu/small_car_f407",
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
$remoteCompose = "$remoteMiddleware/docker/compose.yaml"

try {
  Write-Host "[1/4] Package robot_host and ros_middleware..."
  Push-Location $workspaceRoot
  try {
    $tarArgs = @(
      "-czf", $archivePath,
      "--exclude=robot_host/build*",
      "--exclude=robot_host/install*",
      "--exclude=robot_host/log*",
      "--exclude=robot_host/runtime",
      "robot_host",
      "ros_middleware"
    )
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
    "if [ -f '$remoteCompose' ]; then docker compose -f '$remoteCompose' down; fi",
    "mkdir -p '$remoteRobotHost' '$remoteMiddleware'",
    "rm -rf '$remoteRobotHost/core' '$remoteRobotHost/ros' '$remoteRobotHost/docs' '$remoteRobotHost/scripts' '$remoteRobotHost/tools' '$remoteRobotHost/systemd'",
    "rm -rf '$remoteMiddleware/src' '$remoteMiddleware/config' '$remoteMiddleware/docker' '$remoteMiddleware/docs'",
    "tar -xzf '$remoteArchive' -C '$RemoteWorkspace'",
    "rm -f '$remoteArchive'",
    "if docker image inspect small-car-ros2:kilted >/dev/null 2>&1; then docker run --rm -v '${remoteRobotHost}:/target' small-car-ros2:kilted bash -lc 'rm -rf /target/build-ros /target/install-ros /target/log-ros'; else rm -rf '$remoteRobotHost/build-ros' '$remoteRobotHost/install-ros' '$remoteRobotHost/log-ros'; fi",
    "cmake -S '$remoteRobotHost' -B '$remoteRobotHost/build-host'",
    "cmake --build '$remoteRobotHost/build-host' -j4",
    "ctest --test-dir '$remoteRobotHost/build-host' --output-on-failure",
    "chmod +x '$remoteRobotHost/tools/recover_mcu_usb.sh' '$remoteRobotHost/scripts/update_mcu_firmware.sh'",
    "docker compose -f '$remoteCompose' up --build -d --force-recreate",
    "docker compose -f '$remoteCompose' ps",
    "for attempt in {1..45}; do if docker compose -f '$remoteCompose' exec -T small_car_ros2 bash -lc 'test -f /workspace/smart_car/robot_host/install-ros/setup.bash && source /opt/ros/kilted/setup.bash && source /workspace/smart_car/robot_host/install-ros/setup.bash && timeout 10 ros2 node list | grep -Fx /small_car_base >/dev/null && timeout 10 ros2 topic list | grep -Fx /car/audio/input >/dev/null'; then echo 'ros_health=ok'; exit 0; fi; sleep 2; done; echo 'ROS health check failed' >&2; docker compose -f '$remoteCompose' logs --tail=200; exit 1"
  )
  & ssh -p $SshPort $remoteTarget ($remoteSteps -join " && ")
  if ($LASTEXITCODE -ne 0) { throw "Host deployment failed" }

  Write-Host "[4/4] Deployment complete: $RemoteWorkspace"
} finally {
  if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
  }
}
