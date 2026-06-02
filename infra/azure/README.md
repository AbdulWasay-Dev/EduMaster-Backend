# Azure Backend Deployment

This backend is designed to run on Azure Container Apps with:

- FastAPI/Uvicorn in the existing Docker image
- Tesseract OCR inside the container
- PostgreSQL on Azure Database for PostgreSQL Flexible Server
- ChromaDB persisted on an Azure Files mount at `/app/chroma_db`
- Uploaded files persisted on an Azure Files mount at `/app/uploads`
- HuggingFace/Torch caches persisted on Azure Files so cold starts do less work
- GitHub Actions building the image, pushing to Azure Container Registry, and updating Container Apps

The default replica range is `0..1` to save Azure for Students credit and to avoid multiple replicas writing to the same local ChromaDB files. If you later move vector search to a network service, you can raise `MaxReplicas`.

## 1. Provision Azure

Install Azure CLI, then from the `Backend` folder:

```powershell
az login
az account list --output table

$pgPassword = Read-Host "Postgres admin password" -AsSecureString
$jwtSecret = Read-Host "Backend SECRET_KEY" -AsSecureString

.\infra\azure\provision-backend.ps1 `
  -SubscriptionId "<your-subscription-id>" `
  -Location "eastus" `
  -ResourceGroup "rg-edumaster-prod" `
  -NamePrefix "edumaster" `
  -PostgresAdminPassword $pgPassword `
  -SecretKey $jwtSecret `
  -FrontendOrigin "https://your-frontend-domain.com" `
  -GroqApiKey "<optional-groq-key>" `
  -GoogleApiKey "<optional-google-key>" `
  -MistralApiKey "<optional-mistral-key>"
```

The script prints these GitHub Actions repository variables:

```text
AZURE_RESOURCE_GROUP
AZURE_CONTAINER_APP
AZURE_CONTAINER_REGISTRY
```

Add them in GitHub under `Settings -> Secrets and variables -> Actions -> Variables`.

## 2. Create GitHub OIDC Credentials

Replace `OWNER/REPO` with your backend GitHub repository, then run:

```powershell
$repo = "OWNER/REPO"
$resourceGroup = "rg-edumaster-prod"
$acrName = "<AZURE_CONTAINER_REGISTRY from the provision script>"
$appName = "edumaster-backend-github"

$subscriptionId = az account show --query id --output tsv
$tenantId = az account show --query tenantId --output tsv
$appId = az ad app create --display-name $appName --query appId --output tsv
az ad sp create --id $appId

$rgId = az group show --name $resourceGroup --query id --output tsv
$acrId = az acr show --name $acrName --resource-group $resourceGroup --query id --output tsv

az role assignment create --assignee $appId --role Contributor --scope $rgId
az role assignment create --assignee $appId --role AcrPush --scope $acrId

$credential = @{
  name = "github-main"
  issuer = "https://token.actions.githubusercontent.com"
  subject = "repo:$repo:ref:refs/heads/main"
  audiences = @("api://AzureADTokenExchange")
} | ConvertTo-Json

$credential | Set-Content .\federated-credential.json
az ad app federated-credential create --id $appId --parameters .\federated-credential.json
```

Add these GitHub Actions repository secrets:

```text
AZURE_CLIENT_ID=<appId>
AZURE_TENANT_ID=<tenantId>
AZURE_SUBSCRIPTION_ID=<subscriptionId>
```

## 3. Deploy

Push to `main`. The workflow at `.github/workflows/azure-container-apps.yml` will:

1. Compile the Python app modules.
2. Build the Docker image with OCR, ChromaDB, and local embedding dependencies.
3. Push tags `latest` and the commit SHA to Azure Container Registry.
4. Update the Azure Container App to the commit SHA image.
5. Smoke-test `https://<container-app-fqdn>/health`.

## Notes

- Redis/Celery are not provisioned here because the current backend only defines Redis/Celery settings; no Python module currently imports or uses Redis/Celery. Add Azure Cache for Redis when background workers are actually introduced.
- Azure Files is acceptable for this app while `MaxReplicas=1`. ChromaDB uses local files, so do not scale this container horizontally without changing vector storage.
- PostgreSQL uses `?sslmode=require` in `DATABASE_URL`.
- To update frontend access later:

```powershell
az containerapp update `
  --name "<AZURE_CONTAINER_APP>" `
  --resource-group "<AZURE_RESOURCE_GROUP>" `
  --set-env-vars CORS_ORIGINS="https://your-frontend-domain.com"
```

