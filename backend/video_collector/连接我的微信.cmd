@echo off
chcp 65001 >nul
set "VIDEO_UV_DIR=%USERPROFILE%\.research-video-collector\tools"
set "VIDEO_UV_COMMAND="
for /f "delims=" %%i in ('where uv.exe 2^>nul') do if not defined VIDEO_UV_COMMAND set "VIDEO_UV_COMMAND=%%i"
if defined VIDEO_UV_COMMAND goto ready
if not exist "%VIDEO_UV_DIR%\uv.exe" (
  echo 首次使用，正在自动准备连接环境，请保持网络连接。
  powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $d=$env:VIDEO_UV_DIR; New-Item -ItemType Directory -Force -Path $d | Out-Null; $arch=if($env:PROCESSOR_ARCHITECTURE -eq 'ARM64'){'aarch64'}else{'x86_64'}; $z=Join-Path $d 'uv.zip'; Invoke-WebRequest ('https://github.com/astral-sh/uv/releases/latest/download/uv-'+$arch+'-pc-windows-msvc.zip') -OutFile $z; Expand-Archive $z -DestinationPath (Join-Path $d 'unpacked') -Force; Get-ChildItem (Join-Path $d 'unpacked') -Filter uv.exe -Recurse | Select-Object -First 1 | Copy-Item -Destination (Join-Path $d 'uv.exe')"
  if errorlevel 1 goto failed
)
set "VIDEO_UV_COMMAND=%VIDEO_UV_DIR%\uv.exe"
:ready
cd /d "%~dp0"
echo 正在准备微信连接，已安装的环境会自动复用。请保持此窗口运行。
"%VIDEO_UV_COMMAND%" --no-config run --no-project --python 3.12 --with httpx --with imageio-ffmpeg bootstrap.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo 连接未完成。请检查网络、微信登录状态和操作系统授权后重新双击。
pause
exit /b 1
