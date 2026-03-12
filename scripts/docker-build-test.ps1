# =============================================================================
# Docker Build Test Script for lolo-ai-documents
# =============================================================================
# Run this script to test the Docker build locally before pushing to ECR
# =============================================================================

param(
    [switch]$Run,
    [switch]$Push,
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"

# Configuration
$IMAGE_NAME = "lolo-ai-documents"
$AWS_REGION = "us-west-2"
# Replace with your actual AWS account ID
$AWS_ACCOUNT_ID = "YOUR_AWS_ACCOUNT_ID"
$ECR_REPO = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_NAME"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  LOLO AI Documents - Docker Build Test" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Build the image
Write-Host "[1/4] Building Docker image..." -ForegroundColor Yellow
$buildStart = Get-Date

docker build -t "${IMAGE_NAME}:${Tag}" .

$buildTime = (Get-Date) - $buildStart
Write-Host "Build completed in $($buildTime.TotalSeconds.ToString('F1')) seconds" -ForegroundColor Green
Write-Host ""

# Step 2: Show image size
Write-Host "[2/4] Image details:" -ForegroundColor Yellow
docker images $IMAGE_NAME --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
Write-Host ""

# Step 3: Run container locally (if -Run flag is set)
if ($Run) {
    Write-Host "[3/4] Running container locally..." -ForegroundColor Yellow
    Write-Host "Container will be available at http://localhost:8000" -ForegroundColor Cyan
    Write-Host "Health check: http://localhost:8000/health" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
    Write-Host ""

    # Run with test environment variables
    docker run --rm -it `
        -p 8000:8000 `
        -e ENVIRONMENT=development `
        -e DEBUG=true `
        -e ANTHROPIC_API_KEY=sk-test-key `
        -e MYSQL_HOST=host.docker.internal `
        -e MYSQL_PORT=3306 `
        -e MYSQL_USER=root `
        -e MYSQL_PASSWORD=password `
        -e MYSQL_DATABASE=db_lolo `
        -e AWS_ACCESS_KEY_ID=test `
        -e AWS_SECRET_ACCESS_KEY=test `
        -e AWS_REGION=us-west-2 `
        -e S3_BUCKET_NAME=archivosstorage `
        --name lolo-ai-documents-test `
        "${IMAGE_NAME}:${Tag}"
} else {
    Write-Host "[3/4] Skipping local run (use -Run flag to run locally)" -ForegroundColor DarkGray
}

# Step 4: Push to ECR (if -Push flag is set)
if ($Push) {
    Write-Host "[4/4] Pushing to ECR..." -ForegroundColor Yellow

    # Login to ECR
    Write-Host "Logging in to ECR..." -ForegroundColor Cyan
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REPO

    # Tag for ECR
    docker tag "${IMAGE_NAME}:${Tag}" "${ECR_REPO}:${Tag}"

    # Push
    Write-Host "Pushing image..." -ForegroundColor Cyan
    docker push "${ECR_REPO}:${Tag}"

    Write-Host "Image pushed successfully!" -ForegroundColor Green
    Write-Host "ECR URI: ${ECR_REPO}:${Tag}" -ForegroundColor Cyan
} else {
    Write-Host "[4/4] Skipping ECR push (use -Push flag to push)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Test locally: .\docker-build-test.ps1 -Run" -ForegroundColor White
Write-Host "  2. Push to ECR:  .\docker-build-test.ps1 -Push -Tag v1.0.0" -ForegroundColor White
Write-Host ""
