<#
.SYNOPSIS
    Assina digitalmente executáveis com um certificado de assinatura de código (.pfx).

.DESCRIPTION
    Usado pelo workflow de release. Lê o certificado das variáveis de ambiente
    WINDOWS_CERT_PFX_BASE64 (conteúdo do .pfx em Base64) e WINDOWS_CERT_PASSWORD.
    Sem o certificado configurado, apenas avisa e não faz nada: a release sai sem assinatura.

.EXAMPLE
    .\scripts\assinar.ps1 dist\LeitorUniversal\LeitorUniversal.exe
#>
param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Arquivos)

$ErrorActionPreference = "Stop"
if (-not $env:WINDOWS_CERT_PFX_BASE64) {
    Write-Host "::warning::Certificado não configurado: arquivos publicados sem assinatura digital."
    exit 0
}

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe não encontrado (Windows SDK)." }

$pfx = Join-Path $env:RUNNER_TEMP "certificado.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERT_PFX_BASE64))
try {
    foreach ($arquivo in $Arquivos) {
        & $signtool.FullName sign /f $pfx /p $env:WINDOWS_CERT_PASSWORD /fd SHA256 `
            /tr "http://timestamp.digicert.com" /td SHA256 /d "Leitor Universal" $arquivo
        if ($LASTEXITCODE -ne 0) { throw "Falha ao assinar $arquivo" }
        Write-Host "Assinado: $arquivo"
    }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
