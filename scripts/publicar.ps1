<#
.SYNOPSIS
    Publica uma nova versão do Leitor Universal no GitHub.

.DESCRIPTION
    Roda os testes, incrementa a versão em leitor_universal/__init__.py, cria o commit e a
    tag vX.Y.Z e envia tudo ao GitHub. O workflow "Release" então gera o instalador e publica
    a release; os aplicativos instalados detectam a nova versão automaticamente.

.EXAMPLE
    .\scripts\publicar.ps1                 # 1.2.3 -> 1.2.4 (correção)
    .\scripts\publicar.ps1 -Tipo minor     # 1.2.3 -> 1.3.0 (novidades)
    .\scripts\publicar.ps1 -Versao 2.0.0   # versão explícita
#>
param(
    [ValidateSet("patch", "minor", "major")]
    [string]$Tipo = "patch",
    [string]$Versao
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
$arquivoVersao = Join-Path $raiz "leitor_universal\__init__.py"
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$ramo = git rev-parse --abbrev-ref HEAD
if ($ramo -ne "main") { throw "Publique a partir do ramo main (atual: $ramo)." }

git fetch --quiet origin
if (git status --porcelain) {
    throw "Há alterações não commitadas. Faça commit (git add . ; git commit) antes de publicar."
}
if ((git rev-list --count "HEAD..origin/main") -ne "0") {
    throw "O ramo local está atrás do GitHub. Rode 'git pull' primeiro."
}

$atual = [regex]::Match((Get-Content $arquivoVersao -Raw), '__version__ = "(\d+)\.(\d+)\.(\d+)"')
if (-not $atual.Success) { throw "Não foi possível ler __version__ em $arquivoVersao." }
$maior, $menor, $corr = 1..3 | ForEach-Object { [int]$atual.Groups[$_].Value }

if (-not $Versao) {
    switch ($Tipo) {
        "major" { $Versao = "$($maior + 1).0.0" }
        "minor" { $Versao = "$maior.$($menor + 1).0" }
        default { $Versao = "$maior.$menor.$($corr + 1)" }
    }
}
if ($Versao -notmatch '^\d+\.\d+\.\d+$') { throw "Versão inválida: $Versao (use X.Y.Z)." }
if (git tag --list "v$Versao") { throw "A tag v$Versao já existe." }

$changelog = Join-Path $raiz "CHANGELOG.md"
$textoLog = Get-Content $changelog -Raw -Encoding utf8
$pendente = [regex]::Match($textoLog, '(?ms)^## \[Não publicado\]\s*\n(.*?)(?=^## \[|\z)')
if (-not $pendente.Success -or -not $pendente.Groups[1].Value.Trim()) {
    throw "Descreva as novidades em '## [Não publicado]' no CHANGELOG.md antes de publicar."
}

Write-Host "Executando testes..." -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = "offscreen"
& $python -m pytest -q tests
if ($LASTEXITCODE -ne 0) { throw "Os testes falharam; publicação cancelada." }

Write-Host "Publicando $maior.$menor.$corr -> $Versao" -ForegroundColor Cyan
(Get-Content $arquivoVersao -Raw) -replace '__version__ = "[^"]+"', "__version__ = `"$Versao`"" |
    Set-Content $arquivoVersao -NoNewline -Encoding utf8

$data = Get-Date -Format "yyyy-MM-dd"
$textoLog = $textoLog -replace '(?m)^## \[Não publicado\]', "## [Não publicado]`n`n## [$Versao] - $data"
Set-Content $changelog $textoLog -NoNewline -Encoding utf8

git add $arquivoVersao $changelog
git commit -m "Versão $Versao"
git tag -a "v$Versao" -m "Versão $Versao"
git push origin main
git push origin "v$Versao"

$repo = (git remote get-url origin) -replace '\.git$', '' -replace '^git@github\.com:', 'https://github.com/'
Write-Host ""
Write-Host "Pronto! Acompanhe a geração do instalador em: $repo/actions" -ForegroundColor Green
Write-Host "A release ficará disponível em: $repo/releases/tag/v$Versao" -ForegroundColor Green
