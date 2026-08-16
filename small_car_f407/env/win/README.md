# Windows build environment

This directory contains the reproducible Windows firmware build environment.
The archives are tracked with Git LFS and expanded into the ignored `tools/`
directory by `activate.ps1`.

| Tool | Version | SHA-256 |
| --- | --- | --- |
| Arm GNU Toolchain | 14.3.Rel1 | `864C0C8815857D68A1BBBA2E5E2782255BB922845C71C97636004A3D74F60986` |
| CMake | 4.3.3 | `935ADE9E5E8723583C07F44C5592CEA2A1C8F65C56CA7E07B34C025C880E0BD6` |
| Ninja | 1.13.2 | `07FC8261B42B20E71D1720B39068C2E14FFCEE6396B76FB7A795FB460B78DC65` |

Activate the environment in PowerShell before using the repository presets:

```powershell
git lfs pull
. .\env\win\activate.ps1
cmake --preset Debug
cmake --build --preset Debug
```
