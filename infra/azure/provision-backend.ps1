<#
.SYNOPSIS
Provision Azure resources for the EduMaster backend.

.DESCRIPTION
Creates:
- Azure Container Registry
- Azure Database for PostgreSQL Flexible Server
- Azure Container Apps environment
- Azure Files shares mounted into the container app for uploads, ChromaDB, and model caches
- A placeholder Container App that GitHub Actions can update with the real backend image

Run from the Backend directory after `az login`.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [string]$Location = "eastus",
    [string]$ResourceGroup = "rg-edumaster-prod",
    [string]$NamePrefix = "edumaster",
    [string]$NameSuffix = "",

    [string]$PostgresAdminUser = "edumasteradmin",
    [Parameter(Mandatory = $true)]
    [SecureString]$PostgresAdminPassword,
    [string]$DatabaseName = "edumasterdb",

    [Parameter(Mandatory = $true)]
    [SecureString]$SecretKey,

    [string]$FrontendOrigin = "*",
    [string]$GroqApiKey = "placeholder-groq-key",
    [string]$GroqApiKeys = " ",
    [string]$GoogleApiKey = "placeholder-google-key",
    [string]$MistralApiKey = "placeholder-mistral-key",

    [string]$ContainerImage = "mcr.microsoft.com/k8se/quickstart:latest",
    [double]$Cpu = 2.0,
    [string]$Memory = "4Gi",
    [int]$MinReplicas = 0,
    [int]$MaxReplicas = 1,
    [int]$StorageShareQuotaGiB = 20
)

$ErrorActionPreference = "Stop"

function ConvertTo-PlainText {
    param([Parameter(Mandatory = $true)][SecureString]$Value)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Invoke-AzCli {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    Write-Host "az $($Args -join ' ')" -ForegroundColor DarkGray
    & az @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }
}

function Get-AzCliValue {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    $value = & az @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Args -join ' ')"
    }
    ($value | Out-String).Trim()
}

function Limit-Name {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][int]$MaxLength
    )

    if ($Value.Length -le $MaxLength) {
        return $Value
    }
    $Value.Substring(0, $MaxLength).TrimEnd("-")
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is not installed or is not on PATH."
}

$base = ($NamePrefix.ToLowerInvariant() -replace "[^a-z0-9]", "")
if ($base.Length -lt 3) {
    throw "NamePrefix must contain at least three letters or numbers."
}

$suffix = ($NameSuffix.ToLowerInvariant() -replace "[^a-z0-9]", "")
if ([string]::IsNullOrWhiteSpace($suffix)) {
    $suffix = (($SubscriptionId -replace "-", "").Substring(0, 6)).ToLowerInvariant()
}

$acrName = Limit-Name -Value "$($base)acr$($suffix)" -MaxLength 50
$storageAccountName = Limit-Name -Value "$($base)st$($suffix)" -MaxLength 24
$containerAppName = Limit-Name -Value "$($base)-api" -MaxLength 32
$containerEnvName = Limit-Name -Value "$($base)-env" -MaxLength 32
$postgresServerName = Limit-Name -Value "$($base)-pg-$($suffix)" -MaxLength 63

$pgPassword = ConvertTo-PlainText -Value $PostgresAdminPassword
$jwtSecret = ConvertTo-PlainText -Value $SecretKey
$encodedUser = [uri]::EscapeDataString($PostgresAdminUser)
$encodedPassword = [uri]::EscapeDataString($pgPassword)
$databaseUrl = "postgresql://$encodedUser`:$encodedPassword@$postgresServerName.postgres.database.azure.com:5432/$DatabaseName`?sslmode=require"

$corsOrigins = if ([string]::IsNullOrWhiteSpace($FrontendOrigin)) { "*" } else { $FrontendOrigin }

Write-Host "Provisioning EduMaster backend resources in $Location..." -ForegroundColor Cyan

Invoke-AzCli -Args @("account", "set", "--subscription", $SubscriptionId)
Invoke-AzCli -Args @("extension", "add", "--name", "containerapp", "--upgrade")
Invoke-AzCli -Args @("provider", "register", "--namespace", "Microsoft.App")
Invoke-AzCli -Args @("provider", "register", "--namespace", "Microsoft.OperationalInsights")
Invoke-AzCli -Args @("provider", "register", "--namespace", "Microsoft.DBforPostgreSQL")
Invoke-AzCli -Args @("provider", "register", "--namespace", "Microsoft.Storage")

Invoke-AzCli -Args @("group", "create", "--name", $ResourceGroup, "--location", $Location, "--output", "none")

Invoke-AzCli -Args @(
    "acr", "create",
    "--resource-group", $ResourceGroup,
    "--name", $acrName,
    "--sku", "Basic",
    "--admin-enabled", "false",
    "--output", "none"
)

Invoke-AzCli -Args @(
    "storage", "account", "create",
    "--resource-group", $ResourceGroup,
    "--name", $storageAccountName,
    "--location", $Location,
    "--kind", "StorageV2",
    "--sku", "Standard_LRS",
    "--https-only", "true",
    "--enable-large-file-share",
    "--output", "none"
)

foreach ($share in @("uploads", "chroma", "hf-cache", "torch-cache")) {
    Invoke-AzCli -Args @(
        "storage", "share-rm", "create",
        "--resource-group", $ResourceGroup,
        "--storage-account", $storageAccountName,
        "--name", $share,
        "--quota", "$StorageShareQuotaGiB",
        "--enabled-protocols", "SMB",
        "--output", "none"
    )
}

$storageKey = Get-AzCliValue -Args @(
    "storage", "account", "keys", "list",
    "--resource-group", $ResourceGroup,
    "--account-name", $storageAccountName,
    "--query", "[0].value",
    "--output", "tsv"
)

Invoke-AzCli -Args @(
    "postgres", "flexible-server", "create",
    "--resource-group", $ResourceGroup,
    "--name", $postgresServerName,
    "--location", $Location,
    "--admin-user", $PostgresAdminUser,
    "--admin-password", $pgPassword,
    "--database-name", $DatabaseName,
    "--version", "16",
    "--tier", "Burstable",
    "--sku-name", "Standard_B1ms",
    "--storage-size", "32",
    "--public-access", "0.0.0.0",
    "--output", "none"
)

Invoke-AzCli -Args @(
    "containerapp", "env", "create",
    "--name", $containerEnvName,
    "--resource-group", $ResourceGroup,
    "--location", $Location,
    "--output", "none"
)

foreach ($share in @("uploads", "chroma", "hf-cache", "torch-cache")) {
    Invoke-AzCli -Args @(
        "containerapp", "env", "storage", "set",
        "--name", $containerEnvName,
        "--resource-group", $ResourceGroup,
        "--storage-name", $share,
        "--azure-file-account-name", $storageAccountName,
        "--azure-file-account-key", $storageKey,
        "--azure-file-share-name", $share,
        "--access-mode", "ReadWrite",
        "--output", "none"
    )
}

$appDefinition = @{
    properties = @{
        configuration = @{
            activeRevisionsMode = "Single"
            ingress = @{
                external = $true
                targetPort = 8010
                transport = "auto"
                allowInsecure = $false
            }
            secrets = @(
                @{ name = "database-url"; value = $databaseUrl },
                @{ name = "secret-key"; value = $jwtSecret },
                @{ name = "groq-api-key"; value = $GroqApiKey },
                @{ name = "groq-api-keys"; value = $GroqApiKeys },
                @{ name = "google-api-key"; value = $GoogleApiKey },
                @{ name = "mistral-api-key"; value = $MistralApiKey }
            )
        }
        template = @{
            containers = @(
                @{
                    name = "backend"
                    image = $ContainerImage
                    resources = @{
                        cpu = $Cpu
                        memory = $Memory
                    }
                    env = @(
                        @{ name = "ENVIRONMENT"; value = "production" },
                        @{ name = "DEBUG"; value = "false" },
                        @{ name = "PORT"; value = "8010" },
                        @{ name = "CORS_ORIGINS"; value = $corsOrigins },
                        @{ name = "ALLOWED_HOSTS"; value = "*" },
                        @{ name = "DATABASE_URL"; secretRef = "database-url" },
                        @{ name = "SECRET_KEY"; secretRef = "secret-key" },
                        @{ name = "GROQ_API_KEY"; secretRef = "groq-api-key" },
                        @{ name = "GROQ_API_KEYS"; secretRef = "groq-api-keys" },
                        @{ name = "GOOGLE_API_KEY"; secretRef = "google-api-key" },
                        @{ name = "MISTRAL_API_KEY"; secretRef = "mistral-api-key" },
                        @{ name = "TESSERACT_PATH"; value = "/usr/bin/tesseract" },
                        @{ name = "USE_GOOGLE_VISION"; value = "false" },
                        @{ name = "CHROMA_DB_PATH"; value = "/app/chroma_db" },
                        @{ name = "UPLOAD_PATH"; value = "/app/uploads" },
                        @{ name = "HF_HOME"; value = "/app/.cache/huggingface" },
                        @{ name = "TORCH_HOME"; value = "/app/.cache/torch" },
                        @{ name = "TRANSFORMERS_OFFLINE"; value = "1" },
                        @{ name = "LOCAL_EMBEDDING_MODEL"; value = "BAAI/bge-base-en-v1.5" },
                        @{ name = "MAX_FILE_SIZE"; value = "52428800" },
                        @{ name = "ALLOWED_FILE_TYPES"; value = "pdf,pptx,docx,png,jpg,jpeg" }
                    )
                    volumeMounts = @(
                        @{ volumeName = "uploads"; mountPath = "/app/uploads" },
                        @{ volumeName = "chroma"; mountPath = "/app/chroma_db" },
                        @{ volumeName = "hf-cache"; mountPath = "/app/.cache/huggingface" },
                        @{ volumeName = "torch-cache"; mountPath = "/app/.cache/torch" }
                    )
                }
            )
            scale = @{
                minReplicas = $MinReplicas
                maxReplicas = $MaxReplicas
            }
            volumes = @(
                @{ name = "uploads"; storageType = "AzureFile"; storageName = "uploads" },
                @{ name = "chroma"; storageType = "AzureFile"; storageName = "chroma" },
                @{ name = "hf-cache"; storageType = "AzureFile"; storageName = "hf-cache" },
                @{ name = "torch-cache"; storageType = "AzureFile"; storageName = "torch-cache" }
            )
        }
    }
}

$definitionPath = Join-Path $env:TEMP "$containerAppName.containerapp.json"
$appDefinition | ConvertTo-Json -Depth 50 | Set-Content -Path $definitionPath -Encoding UTF8

Invoke-AzCli -Args @(
    "containerapp", "create",
    "--name", $containerAppName,
    "--resource-group", $ResourceGroup,
    "--environment", $containerEnvName,
    "--yaml", $definitionPath,
    "--output", "none"
)

$fqdn = Get-AzCliValue -Args @(
    "containerapp", "show",
    "--name", $containerAppName,
    "--resource-group", $ResourceGroup,
    "--query", "properties.configuration.ingress.fqdn",
    "--output", "tsv"
)

Invoke-AzCli -Args @(
    "containerapp", "update",
    "--name", $containerAppName,
    "--resource-group", $ResourceGroup,
    "--set-env-vars",
    "ALLOWED_HOSTS=$fqdn",
    "CORS_ORIGINS=$corsOrigins",
    "--output", "none"
)

Invoke-AzCli -Args @(
    "containerapp", "identity", "assign",
    "--name", $containerAppName,
    "--resource-group", $ResourceGroup,
    "--system-assigned",
    "--output", "none"
)

$principalId = Get-AzCliValue -Args @(
    "containerapp", "identity", "show",
    "--name", $containerAppName,
    "--resource-group", $ResourceGroup,
    "--query", "principalId",
    "--output", "tsv"
)

$acrId = Get-AzCliValue -Args @(
    "acr", "show",
    "--name", $acrName,
    "--resource-group", $ResourceGroup,
    "--query", "id",
    "--output", "tsv"
)

try {
    Invoke-AzCli -Args @(
        "role", "assignment", "create",
        "--assignee-object-id", $principalId,
        "--assignee-principal-type", "ServicePrincipal",
        "--role", "AcrPull",
        "--scope", $acrId,
        "--output", "none"
    )
}
catch {
    Write-Warning "Could not create AcrPull role assignment. If it already exists, you can ignore this. Details: $_"
}

Invoke-AzCli -Args @(
    "containerapp", "registry", "set",
    "--name", $containerAppName,
    "--resource-group", $ResourceGroup,
    "--server", "$acrName.azurecr.io",
    "--identity", "system",
    "--output", "none"
)

Write-Host ""
Write-Host "Azure backend scaffold is ready." -ForegroundColor Green
Write-Host "Backend URL: https://$fqdn"
Write-Host ""
Write-Host "Use these GitHub Actions repository variables:"
Write-Host "AZURE_RESOURCE_GROUP=$ResourceGroup"
Write-Host "AZURE_CONTAINER_APP=$containerAppName"
Write-Host "AZURE_CONTAINER_REGISTRY=$acrName"
Write-Host ""
Write-Host "Resource names:"
Write-Host "PostgreSQL server: $postgresServerName"
Write-Host "Database: $DatabaseName"
Write-Host "Storage account: $storageAccountName"
Write-Host "Container Apps environment: $containerEnvName"
