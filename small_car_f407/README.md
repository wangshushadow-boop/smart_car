# small_car_f407

基于 STM32F407 的智能小车固件工程，由 STM32CubeMX 生成基础代码，并使用 CMake 构建。

## 项目结构

- `Core/`：应用代码和 CubeMX 生成的启动、初始化相关代码。
- `Drivers/`：STM32 HAL 库和 CMSIS 设备支持文件。
- `Middlewares/`：第三方中间件，目前包含 FreeRTOS。
- `cmake/`：工具链配置和 CubeMX 生成的 CMake 集成文件。
- `small_car_f407.ioc`：STM32CubeMX 工程配置文件。
- `STM32F407XX_FLASH.ld`：链接脚本。

## 构建

Windows 构建环境已保存在 `env/win/archives/`，其中的大文件通过 Git LFS 管理。
首次克隆后先在当前 PowerShell 会话激活环境（脚本会自动解压工具）：

```powershell
git lfs pull
. .\env\win\activate.ps1
```

然后执行原有的 CMake Preset 命令：

```powershell
cmake --preset Debug
cmake --build --preset Debug
```

Release 构建：

```powershell
cmake --preset Release
cmake --build --preset Release
```

构建产物会输出到 `build/` 目录，该目录不会提交到 Git。

## 开发说明

- 修改 CubeMX 可能重新生成的文件时，自定义代码应放在 `USER CODE BEGIN/END` 区域内。
- 新增应用模块优先放在 `Core/Inc` 和 `Core/Src`。
- 不提交固件二进制、map 文件、目标文件和 IDE 本地配置。
- 硬件参考资料默认放在仓库外；只有需要长期追踪的原理图或资源分配表才放入仓库。

## 文档

- [项目文档](./docs/README.md)
- [C30D V2.2 主板引脚与接线说明](./docs/c30d-v2.2-pinout.md)
