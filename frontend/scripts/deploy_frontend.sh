#!/bin/bash

# Frontend deployment script for both GitHub Actions CD and machine startup
# Usage: ./deploy_machine.sh

set -e  # Exit on any error

# Configuration
PROJECT_PATH="/opt/workflow_app/jobs_manager_front"

# Main deployment function
main() {
    echo "Starting frontend deployment..."

    cd "$PROJECT_PATH"
    CURRENT_USER="$(whoami)"

    # Update code from git
    git switch main
    git fetch origin main
    git reset --hard origin/main
    chmod +x scripts/deploy_frontend.sh
    chown -R "$CURRENT_USER:$CURRENT_USER" "$PROJECT_PATH"

    # Clean previous dependencies before npm ci
    if [ -d node_modules ]; then
        echo "Cleaning existing node_modules..."
        rm -rf node_modules
    fi

    # Install dependencies and build
    npm ci

    # Update schema (graceful fallback if backend unavailable)
    if npm run update-schema 2>/dev/null; then
        echo "API schema updated"
    else
        echo "Using existing schema (backend unavailable)"
    fi

    npm run build

    # Build the training manual (served at /manual/)
    npx vitepress build manual

    # Reload nginx to serve new build
    sudo systemctl reload nginx

    echo "Frontend deployment completed"
}

# Handle script interruption
trap 'echo "Deployment interrupted"; exit 1' INT TERM

main
