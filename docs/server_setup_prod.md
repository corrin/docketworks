# Production Server Setup

**Status:** Underdeveloped — similar to [UAT setup](server_setup_uat.md) but not yet fully documented.

Prod: Hyper-V VM running Ubuntu

## Automated Backups

`scripts/backup_db.sh` runs daily via cron:
- Daily compressed mysqldump to `/var/backups/mysql/`
- Monthly backup copy on the 1st of each month
- Sync to Google Drive via rclone

See `scripts/cleanup_backups.sh` and `scripts/cleanup_backups.py` for backup retention.
