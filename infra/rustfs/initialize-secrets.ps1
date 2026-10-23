$ErrorActionPreference = 'Stop'
$repositoryDirectory = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$secretsDirectory = Join-Path $repositoryDirectory '.docker/rustfs/secrets'
New-Item -ItemType Directory -Force -Path $secretsDirectory | Out-Null

foreach ($credential in @(@{ Name = 'access_key'; Bytes = 10 }, @{ Name = 'secret_key'; Bytes = 32 })) {
    $credentialPath = Join-Path $secretsDirectory $credential.Name
    if (Test-Path -LiteralPath $credentialPath) {
        if ((Get-Item -LiteralPath $credentialPath).Length -eq 0) {
            throw "Empty credential file: $credentialPath"
        }
        continue
    }
    $randomBytes = New-Object byte[] $credential.Bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
    $value = ([BitConverter]::ToString($randomBytes)).Replace('-', '')
    [System.IO.File]::WriteAllText($credentialPath, $value)
}
Write-Output 'RustFS credential files ready'
