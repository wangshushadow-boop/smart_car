# 时间同步

同步链路：公网 NTP → Windows PC (`192.168.3.62`) → WSL / 树莓派 (`192.168.3.85`)。Docker 直接继承树莓派宿主机时间。

## 1. 配置 Windows PC

以管理员身份打开 PowerShell。

配置公网时间源和 64 秒轮询：

```powershell
w32tm.exe /config /manualpeerlist:"ntp.aliyun.com,0x9 time.windows.com,0x9" /syncfromflags:manual /reliable:yes /update
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\Config" /v MinPollInterval /t REG_DWORD /d 6 /f
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\Config" /v MaxPollInterval /t REG_DWORD /d 6 /f
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\Config" /v UpdateInterval /t REG_DWORD /d 100 /f
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\Config" /v FrequencyCorrectRate /t REG_DWORD /d 2 /f
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient" /v SpecialPollInterval /t REG_DWORD /d 64 /f
```

启用 NTP Server：

```powershell
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpServer" /v Enabled /t REG_DWORD /d 1 /f
reg.exe add "HKLM\SYSTEM\CurrentControlSet\Services\W32Time\Config" /v AnnounceFlags /t REG_DWORD /d 5 /f
```

放行局域网 UDP 123：

```powershell
New-NetFirewallRule -DisplayName "Local NTP Server" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 123 -RemoteAddress "192.168.3.0/24" -Profile Private
```

重启并同步：

```powershell
Set-Service w32time -StartupType Automatic
Restart-Service w32time
w32tm.exe /resync /rediscover
```

验证：

```powershell
w32tm.exe /query /source
w32tm.exe /query /status
Get-NetUDPEndpoint -LocalPort 123
```

时间源应为 `ntp.aliyun.com` 或 `time.windows.com`，不能是树莓派。

## 2. 配置树莓派

安装 Chrony 并备份配置：

```bash
sudo apt update
sudo apt install -y chrony
sudo cp /etc/chrony/chrony.conf /etc/chrony/chrony.conf.before-pc-ntp
```

禁用原有公网 pool：

```bash
sudo sed -i '/^[[:space:]]*pool /s/^/# disabled-for-pc-ntp: /' /etc/chrony/chrony.conf
```

配置 PC 时间源：

```bash
echo 'server 192.168.3.62 iburst prefer trust minpoll 4 maxpoll 6' \
  | sudo tee /etc/chrony/sources.d/pc.sources
echo 'maxdistance 10.0' \
  | sudo tee /etc/chrony/conf.d/pc-maxdistance.conf
```

启动并在采集前执行一次校时：

```bash
sudo systemctl enable --now chrony
sudo systemctl restart chrony
sudo chronyc burst 8/8
sudo chronyc makestep
```

验证：

```bash
chronyc sources -v
chronyc tracking
```
System time : 0.000094 seconds fast        系统偏差：0.094 ms
Last offset : +0.000063 seconds            最近偏差：0.063 ms
RMS offset  : 0.000825 seconds             RMS 偏差：0.825 ms
Root delay  : 0.035900 seconds             Root delay：35.9 ms

PC 时间源必须显示为：

```text
^* 192.168.3.62
```

## 3. 配置 WSL

WSL mirrored 网络通过 `127.0.0.1` 访问 Windows NTP Server。

```bash
sudo install -d -m 0755 /etc/systemd/timesyncd.conf.d
sudo tee /etc/systemd/timesyncd.conf.d/10-local-ntp.conf >/dev/null <<'EOF'
[Time]
NTP=127.0.0.1
FallbackNTP=
RootDistanceMaxSec=10
PollIntervalMinSec=16
PollIntervalMaxSec=64
EOF

sudo systemctl enable systemd-timesyncd
sudo systemctl restart systemd-timesyncd
```

验证：

```bash
timedatectl timesync-status
```
应显示：

```text
Server: 127.0.0.1
Leap: normal

Offset: +773us   时钟偏差：0.773 ms
Delay: 1.927ms   网络往返相关延迟：1.927 ms
Jitter: 292us    抖动：0.292 ms
```

## 4. ros2_trace 采集前检查

WSL：

```bash
timedatectl timesync-status
```

树莓派：

```bash
chronyc sources -v
chronyc tracking
```

PC 到树莓派采样：

```powershell
w32tm.exe /stripchart /computer:192.168.3.85 /samples:20 /dataonly
```

要求：

- 树莓派时间源为 `^* 192.168.3.62`。
- WSL 时间源为 `127.0.0.1`。
- 跨机偏差保持在 5 ms 内。
- 采集期间不要执行 `chronyc makestep`、重启 WSL 或手动调整系统时间。

## 5. 恢复树莓派配置

```bash
sudo cp /etc/chrony/chrony.conf.before-pc-ntp /etc/chrony/chrony.conf
sudo rm -f /etc/chrony/sources.d/pc.sources
sudo rm -f /etc/chrony/conf.d/pc-maxdistance.conf
sudo systemctl restart chrony
```
