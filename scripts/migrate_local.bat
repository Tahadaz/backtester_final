@echo off
setlocal
pushd "%~dp0\.."
set DATABASE_URL=postgresql+psycopg2://app:app@127.0.0.1:5555/quant
alembic -c services\api\alembic.ini upgrade head
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
