$ErrorActionPreference = "Stop"
python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
python -m pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
python -m PyInstaller --noconfirm --clean --windowed --onedir `
  --name "RD-Desktop" `
  --collect-data rdclient `
  "RD Desktop.py"
if ($LASTEXITCODE -ne 0) { throw "Windows build failed." }
$selfTest = Start-Process -FilePath ".\dist\RD-Desktop\RD-Desktop.exe" -ArgumentList "--self-test" -Wait -PassThru
if ($selfTest.ExitCode -ne 0) { throw "Packaged application self-test failed." }
Compress-Archive -Path "dist/RD-Desktop/*" -DestinationPath "dist/RD-Desktop-Windows-x64.zip" -Force
