#!/bin/bash

# Log file for auto shutdown script
LOG_FILE="/opt/workflow_app/jobs_manager/logs/auto_shutdown.log"

# Function to log with timestamp
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log_message "Auto shutdown script started"

# Only run on uat hostname
HOSTNAME=$(hostname)
if [ "$HOSTNAME" != "uat" ]; then
    log_message "Not shutting down because hostname is '$HOSTNAME', not 'uat'"
    exit 0
fi

# Check if machine has been on for at least 30 minutes
UPTIME_SECONDS=$(awk '{print int($1)}' /proc/uptime)
if [ $UPTIME_SECONDS -lt 1800 ]; then
    UPTIME_MINUTES=$((UPTIME_SECONDS / 60))
    log_message "Not shutting down because machine was recently started ($UPTIME_MINUTES minutes ago, need 30+ minutes)"
    exit 0
fi

# Check last access time from access.log
LAST_ACCESS=$(stat -c %Y /opt/workflow_app/jobs_manager/logs/access.log 2>/dev/null || echo 0)
CURRENT_TIME=$(date +%s)
IDLE_TIME=$((CURRENT_TIME - LAST_ACCESS))
IDLE_MINUTES=$((IDLE_TIME / 60))

# If idle for more than 30 minutes (1800 seconds), schedule shutdown
if [ $IDLE_TIME -gt 1800 ]; then
    log_message "Scheduling shutdown - website was last accessed $IDLE_MINUTES minutes ago"
    /sbin/shutdown -h 5
else
    log_message "Not shutting down because website was last accessed $IDLE_MINUTES minutes ago (need 30+ minutes idle)"
fi

log_message "Auto shutdown script completed"
