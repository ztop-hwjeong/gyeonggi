@echo off
setlocal
pushd "%~dp0..\..\.."
set "PYTHONPATH=%~dp0src"
uv run --project "%~dp0." --locked python -m compose.provider %*
set "PROVIDER_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %PROVIDER_EXIT_CODE%
