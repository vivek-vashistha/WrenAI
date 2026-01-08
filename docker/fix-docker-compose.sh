#!/bin/bash
# Script to fix docker-compose 1.29.2 bug with legacy containers
# Run this on your EC2 instance

set -e

echo "Stopping all containers..."
docker stop $(docker ps -aq) 2>/dev/null || true

echo "Removing all containers..."
docker rm -f $(docker ps -aq) 2>/dev/null || true

echo "Removing orphan container wrenai-wren-ui-1..."
docker rm -f wrenai-wren-ui-1 2>/dev/null || true

echo "Cleaning up containers with problematic labels..."
# Find and remove containers with compose labels that might cause issues
docker ps -a --filter "label=com.docker.compose.project" --format "{{.ID}}" | xargs -r docker rm -f 2>/dev/null || true

echo "Pruning stopped containers..."
docker container prune -f

echo "Now try starting docker-compose again:"
echo "docker-compose -f docker-compose-dev.yaml --env-file .env up -d"
