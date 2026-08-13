# WSL 大模型环境构建与迁移手册

本文记录当前小车大模型主机的 WSL2 构建过程，适用于：

- 在新主机上从零重建环境；
- 将现有 WSL 环境整体迁移到其他磁盘或其他 Windows 主机；
- 环境损坏后根据备份恢复；
- 核对 MiniCPM-o 4.5 AWQ 的运行条件。

## 1. 当前环境基线

| 项目 | 当前配置 |
| --- | --- |
| Windows WSL | WSL2 2.7.11.0 |
| Linux 发行版 | Ubuntu 24.04，发行版名 `Ubuntu-24.04` |
| WSL 数据位置 | `D:\WSL\Ubuntu-24.04` |
| Linux 默认用户 | `llm_agent`，UID/GID 1000，属于 `sudo` 组 |
| Linux 主目录 | `/home/llm_agent` |
| 默认 Shell | `/usr/bin/zsh` |
| GPU | NVIDIA GeForce RTX 3090 24 GB |
| 通用 Agent 环境 | `llm_agent/py_env/venvs/agent` |
| MiniCPM 环境 | `llm_agent/py_env/venvs/minicpm` |
| 模型目录 | `/mnt/d/AI/models/MiniCPM-o-4_5-AWQ` |
| 推理框架 | vLLM 0.26.0 |
| 模型服务名 | `minicpm-o-4.5-awq` |
| API 地址 | `http://127.0.0.1:8099/v1` |

Ubuntu 的根文件系统保存在：

```text
D:\WSL\Ubuntu-24.04\ext4.vhdx
```

模型、Python 环境及 Linux 用户数据都包含在该 VHDX 中。Windows 的 WSL
运行程序仍位于 `C:\Program Files\WSL`，无法随发行版一起迁移到 D 盘。

### 本次构建使用的安装文件

以下信息用于审计和复现本次安装，不代表未来必须继续使用相同版本：

| 文件 | SHA256 |
| --- | --- |
| `wsl.2.7.11.0.x64.msi` | `A611DDACEE689D2FB1FB5319E58AF7F3998864D86CDCE632EADD8E61614A0F9D` |
| `ubuntu-24.04.4-wsl-amd64.wsl` | `9B2F7730DC68227DD04A9F3E5EAB86AD85CAF556B8606AD94F1F29FF5C4FD3F5` |

WSL MSI 已验证 Authenticode 签名有效且签发者为 Microsoft Corporation；Ubuntu
镜像校验值来自阿里云 Ubuntu 镜像站对应的 `SHA256SUMS`。以后下载新版本时必须
重新查验新文件的签名或校验值，不能套用上表。

## 2. 两种迁移方式

### 2.1 推荐：整体导出与导入

使用 `wsl --export` 和 `wsl --import` 可以同时迁移 Linux 软件包、用户、
Python 虚拟环境、模型和配置，最适合当前环境。

优点：恢复快、遗漏少，不需要重新下载十几 GB 模型。

注意：Windows NVIDIA 驱动、WSL Windows 运行时和可选功能仍需在新主机上
单独安装。

### 2.2 从零重建

根据本文重新安装 Ubuntu、Python、vLLM 和模型。适用于：

- 希望清理旧环境；
- 跨架构或系统版本不兼容；
- 没有完整 WSL 备份；
- 需要升级主要软件版本。

## 3. 新主机前置条件

1. Windows 11 或支持 WSL2 的 Windows 10。
2. BIOS 中启用 CPU 虚拟化。
3. 安装支持 WSL CUDA 的 NVIDIA Windows 驱动。
4. D 盘建议预留至少 60 GB；长期使用建议预留 100 GB 以上。
5. 使用管理员 PowerShell 完成 Windows 功能安装。

启用 WSL 和虚拟机平台：

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

重启 Windows，然后安装或更新 WSL：

```powershell
wsl --update
wsl --version
wsl --set-default-version 2
```

如果 Microsoft Store 或 GitHub 下载不稳定，可以下载官方 WSL x64 MSI 后离线
安装。安装包必须核验数字签名为 Microsoft Corporation。

## 4. 整体迁移现有 WSL

以下命令均在 Windows PowerShell 中运行。

### 4.1 停止模型和 WSL

先进入 WSL 停止模型：

```powershell
wsl -d Ubuntu-24.04
```

```bash
cd /mnt/d/work/smart_car/llm_agent
# 模型以前台方式运行；先在启动模型的终端按 Ctrl+C。
exit
```

关闭整个发行版：

```powershell
wsl --terminate Ubuntu-24.04
wsl --list --verbose
```

确认 `Ubuntu-24.04` 不再显示 `Running`。

### 4.2 导出备份

创建备份目录：

```powershell
New-Item -ItemType Directory -Force D:\WSL_Backup
```

推荐导出为 VHD，以最大程度保留当前文件系统：

```powershell
wsl --export Ubuntu-24.04 D:\WSL_Backup\Ubuntu-24.04.vhdx --vhd
```

如果目标 WSL 不支持 `--vhd`，可导出 tar：

```powershell
wsl --export Ubuntu-24.04 D:\WSL_Backup\Ubuntu-24.04.tar
```

计算备份校验值并单独保存：

```powershell
Get-FileHash D:\WSL_Backup\Ubuntu-24.04.vhdx -Algorithm SHA256
```

不要在校验和备份完成前执行 `wsl --unregister`。该命令会删除原发行版数据。

### 4.3 在新主机或新磁盘导入

创建目标目录：

```powershell
New-Item -ItemType Directory -Force D:\WSL\Ubuntu-24.04
```

从 VHD 导入：

```powershell
wsl --import-in-place Ubuntu-24.04 D:\WSL_Backup\Ubuntu-24.04.vhdx
```

如果使用 tar 备份：

```powershell
wsl --import Ubuntu-24.04 D:\WSL\Ubuntu-24.04 D:\WSL_Backup\Ubuntu-24.04.tar --version 2
```

对于 VHD 导入，如果希望备份文件与运行文件分开，应先复制 VHDX 到最终位置：

```powershell
Copy-Item D:\WSL_Backup\Ubuntu-24.04.vhdx D:\WSL\Ubuntu-24.04\ext4.vhdx
wsl --import-in-place Ubuntu-24.04 D:\WSL\Ubuntu-24.04\ext4.vhdx
```

设置默认用户：

```powershell
wsl --manage Ubuntu-24.04 --set-default-user llm_agent
```

验证：

```powershell
wsl --list --verbose
wsl -d Ubuntu-24.04 -- whoami
wsl -d Ubuntu-24.04 -- printenv HOME
```

预期结果分别包含 WSL2、`llm_agent` 和 `/home/llm_agent`。

## 5. 从零安装 Ubuntu 到 D 盘

### 5.1 获取 Ubuntu WSL 镜像

当前环境使用 Ubuntu 24.04 WSL AMD64 镜像。国内可从阿里云 Ubuntu 镜像站获取，
下载后必须使用同目录 `SHA256SUMS` 校验文件。

当前曾使用的镜像文件名：

```text
ubuntu-24.04.4-wsl-amd64.wsl
```

镜像版本会更新，不应永久依赖该文件名。下载时选择最新 Ubuntu 24.04 LTS 的
WSL AMD64 镜像，并以镜像站公布的校验值为准。

### 5.2 直接安装到 D 盘

较新 WSL 可以指定安装位置：

```powershell
wsl --install --from-file D:\AI\downloads\ubuntu-24.04.4-wsl-amd64.wsl `
  --location D:\WSL\Ubuntu-24.04 `
  --name Ubuntu-24.04
```

如果当前 WSL 不支持这些参数，可先安装临时发行版，再通过
`wsl --export`、`wsl --unregister`、`wsl --import` 迁移到 D 盘。

检查结果：

```powershell
wsl --list --verbose
```

## 6. 创建默认 Linux 用户

新安装镜像首次可能以 root 登录。进入 root Shell：

```powershell
wsl -d Ubuntu-24.04 -u root
```

创建用户并加入 sudo 组：

```bash
useradd --create-home --shell /bin/bash llm_agent
passwd llm_agent
usermod -aG sudo llm_agent
```

退出 WSL，在 PowerShell 中设置默认用户：

```powershell
wsl --manage Ubuntu-24.04 --set-default-user llm_agent
```

验证 UID、用户组和主目录：

```powershell
wsl -d Ubuntu-24.04 -- id
wsl -d Ubuntu-24.04 -- printenv HOME
```

## 7. 配置国内 Ubuntu 软件源

修改 `/etc/apt/sources.list.d/ubuntu.sources` 前先备份原文件：

```bash
sudo cp /etc/apt/sources.list.d/ubuntu.sources \
  /etc/apt/sources.list.d/ubuntu.sources.bak
```

将官方 Ubuntu URI 替换为：

```text
https://mirrors.aliyun.com/ubuntu/
```

随后执行：

```bash
sudo apt-get update
sudo apt-get install -y \
  python3.12 python3.12-venv python3-pip \
  git git-lfs curl ffmpeg build-essential pkg-config libsndfile1
```

## 8. 安装 Zsh 和基础插件

```bash
sudo apt-get install -y \
  zsh zsh-autosuggestions zsh-syntax-highlighting fzf
```

安装仓库中的配置模板并设置默认 Shell：

```bash
install -m 0644 \
  /mnt/d/work/smart_car/llm_agent/config/zshrc \
  /home/llm_agent/.zshrc
sudo chsh -s /usr/bin/zsh llm_agent
```

重新进入 WSL 后验证：

```bash
echo "$SHELL"
echo "$ZSH_VERSION"
```

## 9. 验证 WSL GPU

WSL 内不要额外安装 Linux NVIDIA 内核驱动，GPU 驱动由 Windows 提供。

```bash
nvidia-smi
```

应能看到 RTX 3090、Windows 驱动版本和 24576 MiB 显存。

## 10. 创建模型运行环境

创建目录并授权：

```bash
sudo mkdir -p /opt/models /opt/huggingface /opt/minicpm-service
sudo chown -R llm_agent:llm_agent \
  /opt/models /opt/huggingface /opt/minicpm-service
```

创建虚拟环境：

```bash
cd /mnt/d/work/smart_car
bash ./llm_agent/py_env/install_python_envs.sh
```

使用清华 PyPI 镜像安装 Python 包：

```bash
python -m pip install --upgrade pip \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

python -m pip install \
  vllm==0.26.0 modelscope openai \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

vLLM 的依赖会安装匹配版本的 PyTorch 和 CUDA 用户态运行库。安装完成后验证：

```bash
python -c "import torch; print(torch.__version__); \
print(torch.cuda.is_available()); print(torch.cuda.get_device_name())"
vllm --version
```

## 11. 下载 MiniCPM-o 4.5 AWQ

使用 ModelScope 国内源下载：

```bash
source llm_agent/py_env/venvs/minicpm/bin/activate
modelscope download \
  --model OpenBMB/MiniCPM-o-4_5-AWQ \
  --local_dir /opt/models/MiniCPM-o-4_5-AWQ
```

检查模型文件：

```bash
du -sh /opt/models/MiniCPM-o-4_5-AWQ
find /opt/models/MiniCPM-o-4_5-AWQ -maxdepth 1 -type f | sort
```

模型仓库名称、命令行参数可能随 ModelScope 客户端更新。下载失败时先在
ModelScope 页面确认当前仓库 ID。

## 12. 启动 MiniCPM-o

进入项目目录并启动当前 Omni 服务：

```bash
cd /mnt/d/work/smart_car/llm_agent
./scripts/start_minicpm_omni.sh
```

启动脚本使用两个 WSL 兼容参数：

```text
VLLM_USE_V2_MODEL_RUNNER=0
VLLM_USE_FLASHINFER_SAMPLER=0
```

原因：

- vLLM 0.26 的 V2 Runner 在当前 WSL GPU 映射中要求 UVA，会报
  `RuntimeError: UVA is not available`；
- FlashInfer 采样器可能现场调用 `nvcc`，在没有完整 CUDA Toolkit 时会报
  `Could not find nvcc`；关闭后使用 vLLM 自带采样器，无需安装数 GB 的
  CUDA Toolkit。

启动脚本以前台方式运行。请保持该 WSL 终端打开，另开终端检查状态：

```bash
cd /mnt/d/work/smart_car/llm_agent
curl --noproxy '*' -fsS http://127.0.0.1:8099/health
curl --noproxy '*' -fsS http://127.0.0.1:8099/v1/models
```

启动脚本绑定 `0.0.0.0:8099` 且当前没有 API 鉴权。迁移后必须确认 Windows/WSL 防火墙没有将该端口
暴露到不受信任网络；Agent 本机调用统一使用 `127.0.0.1`。

## 13. 迁移后的完整验收

### 13.1 Windows 与 WSL

```powershell
wsl --version
wsl --list --verbose
wsl -d Ubuntu-24.04 -- whoami
```

### 13.2 Linux、Shell 与磁盘

```bash
echo "$HOME"
echo "$SHELL"
df -h /
du -sh /opt/models /opt/minicpm-service /home/llm_agent
```

### 13.3 GPU 与 Python

```bash
nvidia-smi
source llm_agent/py_env/venvs/minicpm/bin/activate
python -c "import torch; print(torch.cuda.is_available(), \
torch.cuda.get_device_name(), torch.cuda.get_device_properties(0).total_memory)"
```

### 13.4 API

```bash
curl --noproxy '*' -fsS http://127.0.0.1:8099/v1/models
```

预期返回模型 ID：

```text
/mnt/d/AI/models/MiniCPM-o-4_5-AWQ
```

## 14. 备份建议

建议同时备份以下内容：

1. WSL 导出文件及 SHA256；
2. `D:\work\smart_car` Git 仓库；
3. Agent 的本地配置和记忆数据库；
4. API 密钥及云服务凭据，使用密码管理器保存；
5. Windows NVIDIA 驱动版本和 WSL 版本记录。

模型已包含在 WSL 整体备份中。如果还单独备份模型，会额外占用约十几 GB。

不要仅复制正在运行中的 `ext4.vhdx` 作为备份。应先执行
`wsl --terminate Ubuntu-24.04`，再使用 `wsl --export`，避免得到不一致的文件系统。

## 15. 常见故障

树莓派 ROS 2 双向 DDS 配置与验证见
[`robot_host/docs/wsl_raspberry_pi_ros.md`](../../robot_host/docs/wsl_raspberry_pi_ros.md)。

### `UVA is not available`

确认启动环境包含：

```bash
export VLLM_USE_V2_MODEL_RUNNER=0
```

### `Could not find nvcc`

确认包含：

```bash
export VLLM_USE_FLASHINFER_SAMPLER=0
```

### Windows 能识别显卡，但 WSL 中 `nvidia-smi` 失败

1. 更新 Windows NVIDIA 驱动；
2. 执行 `wsl --update`；
3. 执行 `wsl --shutdown` 后重新进入；
4. 不要在 WSL 中安装 Linux NVIDIA 内核驱动。

### 模型脚本启动后立即停止

不要用简单的 `nohup ... &` 脱离所有 WSL 客户端。当前脚本以前台方式运行，
需保持启动它的 WSL 终端。若需要 Windows 登录后自动启动，应单独配置 Windows
任务计划，让任务持续持有 `wsl.exe` 进程。

### C 盘仍有 WSL 占用

这是正常现象。发行版 VHDX、模型和 Python 环境位于 D 盘，但以下组件仍会使用
C 盘：

- `C:\Program Files\WSL` 中的 WSL 运行时；
- Windows 可选功能和系统驱动；
- 少量临时文件及可能的交换文件。
