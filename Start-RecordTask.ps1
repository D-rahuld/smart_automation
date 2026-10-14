$ErrorActionPreference = "Stop"

# Start this script from the project root or keep it in the project root.
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv313\Scripts\python.exe"
$app = Join-Path $projectRoot "src\app.py"

if (-not (Test-Path $python)) {
    Write-Host "ERROR: Project Python environment was not found:" -ForegroundColor Red
    Write-Host $python
    Write-Host "Place Start-RecordTask.ps1 in the project root, beside .venv313 and src."
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $app)) {
    Write-Host "ERROR: App file was not found: $app" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Set-Location $projectRoot

Write-Host "Checking PaddleOCR in the project's virtual environment..."
& $python -c "import paddle, yaml, numpy; from paddleocr import PaddleOCR; print('PaddlePaddle:', paddle.__version__); print('PyYAML:', yaml.__version__); print('NumPy:', numpy.__version__); print('PaddleOCR import successful')"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: PaddleOCR cannot be imported from .venv313." -ForegroundColor Red
    Write-Host "No packages were installed or changed. Run your dependency installation command once to repair this environment."
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Starting Record Task with .venv313..."
& $python $app
