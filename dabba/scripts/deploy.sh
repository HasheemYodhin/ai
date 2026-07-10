#!/usr/bin/env bash
set -euo pipefail

# Dabba Deploy Script
# Builds and deploys the Dabba Docker container

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Default values
DOCKER_TAG=${DOCKER_TAG:-"dabba:latest"}
DOCKER_FILE=${DOCKER_FILE:-"Dockerfile"}
DOCKER_CONTEXT=${DOCKER_CONTEXT:-"."}
NO_CACHE=${NO_CACHE:-false}
PUSH=${PUSH:-false}
REGISTRY=${REGISTRY:-""}

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Deploying Dabba...${NC}"
echo "Tag: $DOCKER_TAG"
echo ""

# Build arguments
BUILD_ARGS=()
BUILD_ARGS+=("-t")
BUILD_ARGS+=("$DOCKER_TAG")
BUILD_ARGS+=("-f")
BUILD_ARGS+=("$DOCKER_FILE")

if [ "$NO_CACHE" = true ]; then
    BUILD_ARGS+=("--no-cache")
fi

BUILD_ARGS+=("$DOCKER_CONTEXT")

# Build the image
echo -e "${YELLOW}Building Docker image...${NC}"
set -x
docker build "${BUILD_ARGS[@]}"
set +x

echo -e "${GREEN}Build complete: $DOCKER_TAG${NC}"

# Push to registry if requested
if [ "$PUSH" = true ]; then
    if [ -n "$REGISTRY" ]; then
        REMOTE_TAG="${REGISTRY}/${DOCKER_TAG}"
        echo -e "${YELLOW}Pushing to $REMOTE_TAG...${NC}"
        docker tag "$DOCKER_TAG" "$REMOTE_TAG"
        docker push "$REMOTE_TAG"
        echo -e "${GREEN}Push complete: $REMOTE_TAG${NC}"
    else
        echo -e "${RED}Error: REGISTRY must be set when PUSH=true${NC}"
        exit 1
    fi
fi

# Run container locally
echo -e "${YELLOW}Starting container...${NC}"
docker-compose up -d

echo -e "${GREEN}Deployment complete!${NC}"
echo "Server running at http://localhost:8000"
echo "Health check: http://localhost:8000/health"
