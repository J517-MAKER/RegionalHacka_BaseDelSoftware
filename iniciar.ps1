<#
  NEXO · preparar y arrancar en este equipo (Windows PowerShell 5.1 o superior).

  Uso, desde la carpeta del proyecto:
      powershell -ExecutionPolicy Bypass -File .\iniciar.ps1                # prepara y arranca
      powershell -ExecutionPolicy Bypass -File .\iniciar.ps1 -Diagnostico   # sólo revisa el equipo

  Qué hace, en orden:
    1. Busca Python 3.11 o superior (lanzador «py» o «python» del PATH).
    2. Si .venv existe pero fue copiado de otra computadora (OneDrive, ZIP, USB) y ya no
       arranca, lo repara apuntándolo al Python de este equipo cuando la versión coincide; si
       no coincide, lo aparta como .venv-otra-maquina-<fecha> (no borra nada) y crea uno nuevo.
    3. Instala requirements.txt sólo si falta algún paquete.
    4. Ejecuta el diagnóstico (python -m services.diagnostico) y arranca NEXO (python main.py).
  No usa Docker: la base de datos local (data\nexo.db) se crea sola.
#>
param([switch]$Diagnostico)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot
$venv = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$config = Join-Path $venv 'pyvenv.cfg'

function Test-Python([string]$exe) {
    if (-not (Test-Path $exe)) { return $false }
    try {
        $out = & $exe -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch { return $false }
}

function Find-SystemPython([string]$version) {
    # Con versión («3.13») se busca exactamente esa; sin versión, la más reciente disponible.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $flag = if ($version) { "-$version" } else { '-3' }
        try {
            $exe = & py $flag -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { $candidates += "$exe".Trim() }
        } catch { }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source -notlike '*WindowsApps*') { $candidates += $onPath.Source }
    foreach ($exe in $candidates) {
        if (-not (Test-Python $exe)) { continue }
        if (-not $version) { return $exe }
        $found = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ("$found".Trim() -eq $version) { return $exe }
    }
    return $null
}

Write-Host 'NEXO · preparando el entorno…' -ForegroundColor Cyan

if ((Test-Path $venvPython) -and -not (Test-Python $venvPython) -and (Test-Path $config)) {
    # .venv copiado de otra máquina: su pyvenv.cfg apunta a un Python que aquí no existe.
    $line = Select-String -Path $config -Pattern '^\s*version\s*=\s*(\d+)\.(\d+)' | Select-Object -First 1
    $wanted = if ($line) { "$($line.Matches[0].Groups[1].Value).$($line.Matches[0].Groups[2].Value)" } else { '' }
    $local = if ($wanted) { Find-SystemPython $wanted } else { $null }
    if ($local) {
        Write-Host "  .venv venía de otra computadora: se apunta al Python $wanted de este equipo ($local)."
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item $config "$config.respaldo-$stamp"
        $home_ = Split-Path $local -Parent
        $text = Get-Content $config
        $text = $text -replace '^\s*home\s*=.*$', "home = $home_"
        $text = $text -replace '^\s*executable\s*=.*$', "executable = $local"
        $text = $text -replace '^\s*command\s*=.*$', "command = $local -m venv $venv"
        [System.IO.File]::WriteAllLines($config, [string[]]$text)  # UTF-8 sin BOM, como lo escribe venv
    }
    if (-not (Test-Python $venvPython)) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $aside = "$venv-otra-maquina-$stamp"
        Write-Host "  No se pudo reparar .venv: se aparta como $aside y se crea uno nuevo." -ForegroundColor Yellow
        Rename-Item -Path $venv -NewName (Split-Path $aside -Leaf)
    }
}

if (-not (Test-Path $venvPython)) {
    $system = Find-SystemPython ''
    if (-not $system) {
        Write-Host 'No se encontró Python 3.11 o superior. Instálalo desde https://www.python.org/downloads/ ' `
                   'marcando «Add python.exe to PATH» y vuelve a ejecutar este script.' -ForegroundColor Red
        exit 1
    }
    Write-Host "  Creando .venv con $system…"
    & $system -m venv $venv
}

& $venvPython -c "import nicegui, cv2, av, numpy, sounddevice, faster_whisper, insightface, onnxruntime, pymupdf" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  Instalando dependencias (requirements.txt)…'
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host 'La instalación de dependencias falló.' -ForegroundColor Red; exit 1 }
}

$env:PYTHONIOENCODING = 'utf-8'
$env:OPENCV_LOG_LEVEL = 'ERROR'  # sin los avisos internos de OpenCV al contar cámaras
& $venvPython -m services.diagnostico
if ($Diagnostico) { exit $LASTEXITCODE }

Write-Host "`nArrancando NEXO en http://127.0.0.1:8080 (Ctrl+C para detenerlo)…" -ForegroundColor Cyan
& $venvPython main.py
