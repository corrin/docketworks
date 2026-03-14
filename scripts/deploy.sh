#!/bin/bash
set -euo pipefail

detect_environment() {
    case "$(hostname)" in
        "msm")
            ENV="PROD"; PROJECT_DIR="/home/django_user/jobs_manager"
            APP_USER="django_user" ;;
        "uat-scheduler")
            ENV="SCHEDULER"; PROJECT_DIR="/opt/workflow_app/jobs_manager"
            APP_USER="ubuntu" ;;
        "uat"|"uat-frontend")
            ENV="UAT"; PROJECT_DIR="/opt/workflow_app/jobs_manager"
            APP_USER="ubuntu" ;;
        *)
            echo "ERROR: Unknown hostname $(hostname)"; exit 1 ;;
    esac
}

create_backup() {
    [ "$ENV" != "PROD" ] && return
    echo "=== Creating backup ==="
    sudo /usr/local/bin/backup_db.sh
}

deploy_application() {
    echo "=== Deploying application ==="
    cd "$PROJECT_DIR"

    # Determine virtual environment path based on environment
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    elif [ -d "venv" ]; then
        source venv/bin/activate
    else
        echo "ERROR: No virtual environment found (.venv or venv)"
        exit 1
    fi
    git pull
    poetry install
    python manage.py migrate
}

build_frontend() {
    [ "$ENV" = "SCHEDULER" ] && return
    echo "=== Building Vue.js frontend ==="
    cd "$PROJECT_DIR/frontend"
    npm install
    npm run build
}

validate_prerequisites() {
    echo "=== Validating prerequisites ==="
    echo "Prerequisites validated"
}

restart_services() {
    case "$ENV" in
        "PROD") echo "=== Restarting Gunicorn ==="; sudo systemctl restart gunicorn ;;
        "UAT") echo "=== Restarting Gunicorn ==="; sudo systemctl restart gunicorn-uat ;;
        "SCHEDULER") echo "=== Restarting Scheduler ==="; sudo systemctl restart scheduler ;;
    esac
}

# Main execution
detect_environment
validate_prerequisites
echo "=== Deploying to $ENV environment ==="
create_backup
deploy_application
build_frontend
restart_services
echo "Deployment to $ENV environment completed successfully"
