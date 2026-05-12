$ErrorActionPreference = "Stop"

python -m PyInstaller `
  --onefile `
  --name bt-bloomberg-bridge `
  --collect-all pandas `
  --collect-all pyarrow `
  .\bridge.py
