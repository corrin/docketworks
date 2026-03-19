# Django Environment Setup

Dev: Windows, WSL, or MacOS.
UAT: Ubuntu. Runs in AWS currently. Oracle is considered as a replacement
Prod: Hyper-V VM running Ubuntu

Note that I currently have UAT split over two VMs (a scheduler on 24/7 and a main app on as needed)

This document outlines the steps to recreate the Django environment from scratch. This includes UAT and PROD specific details which may not apply to other installs

---

## 1. AWS EC2 Setup (UAT ONLY)

**Reviewed**

- The instance must be created in VPC `vpc-00fed508b33af6502` (msm-workflow-vpc)
- Use instance type `t4g.small` (ARM, 2 vCPU burstable, 2GB RAM)
- Launch an EC2 instance running Ubuntu 22.04 ARM
- Assign an Elastic IP address
- Open inbound ports 22, 80, and 443 in the security group
- All environment setup steps below assume a fresh Ubuntu install.

---

## 2. Initial Server Bootstrapping

You can restore from prod data in dev or UAT by running the docs/backup-restore-process.md
For prod, get a recent backup from Google Drive.

### 2.1. Connect via SSH

```bash
ssh -i ~/.ssh/hps.pem ubuntu@<elastic-ip>
```

### 2.2. Update & Install Base Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip mariadb-client git
```

### 2.3. Install Dropbox Client (UAT & PROD only)

```bash
# Download and install Dropbox headless client
cd /tmp
# For ARM64 (t4g instances)
wget -O dropbox.tar.gz "https://www.dropbox.com/download?plat=lnx.aarch64"
# For x86_64 use: wget -O dropbox.tar.gz "https://www.dropbox.com/download?plat=lnx.x86_64"
sudo tar xzf dropbox.tar.gz --strip 1 -C /usr/local/bin

# Create Dropbox folder and set permissions
sudo mkdir -p /opt/dropbox
sudo chown -R $USER:$USER /opt/dropbox

# Start Dropbox daemon (will prompt for account linking)
/usr/local/bin/dropboxd &
```

Install Poetry globally:

```bash
curl -sSL https://install.python-poetry.org | python3.12 -
export PATH="$HOME/.local/bin:$PATH"
```

---

## 3. Project Deployment

### 3.1. Clone Repository

**Reviewed – UAT uses /opt, production uses /home/django_user**

```bash
mkdir -p /opt/workflow_app && cd /opt/workflow_app
# For production, use /home/django_user instead
# mkdir -p /home/django_user && cd /home/django_user

git clone https://github.com/corrin/jobs_manager.git

git clone https://github.com/corrin/jobs_manager_front.git

```

### 3.2. Set Up Python Environment

```bash
cd /opt/workflow_app/jobs_manager
poetry config virtualenvs.in-project true
poetry env remove python3.12 || true
poetry env use python3.12
poetry install
source .venv/bin/activate
```

---

## 4. Environment Configuration

**TO BE REVIEWED**

- For dev: copy `.env.example` to `.env`
- For UAT: Copy `.env.uat` (from dev) to `.env`
  - **Current UAT Instance ID**: `i-0db10a8a884664276` (set in `UAT_INSTANCE_ID`)
- For prod: use the backup in Google Drive

---

## 5. Database Setup

**TO BE REVIEWED**

- Use external RDS MariaDB instance
- Ensure security group allows access from EC2

---

## 6. Running the Application

**TO BE REVIEWED**

### 7.1. Gunicorn (optional)

```bash
.venv/bin/gunicorn jobs_manager.wsgi:application
```

### 7.2. Django Dev Server (if applicable)

```bash
python manage.py runserver 0.0.0.0:8000
```

---

## 8. Nginx Setup

**TO BE REVIEWED**

- Create reverse proxy config to forward to Gunicorn or Django server

## 9. SSL Certificate Setup

**Reviewed**

Install Certbot for automatic SSL certificate management:

```bash
sudo apt install python3-certbot-nginx
```

Generate SSL certificate for the domain:

UAT:

```bash
sudo certbot --nginx -d uat-office.morrissheetmetal.co.nz
```

PROD:

```bash
sudo certbot --nginx -d office.morrissheetmetal.co.nz
```

DEV:

```bash
lt --port 8000 --subdomain msm-corrin
```

Certbot will automatically:

- Generate Let's Encrypt SSL certificate
- Update Nginx configuration for HTTPS
- Set up automatic certificate renewal

---

## 9. Scheduler Service Setup (Scheduler Machine Only)

For the dedicated scheduler machine, install the scheduler as a systemd service:

```bash
# Mark machine as scheduler-only
sudo touch /etc/SCHEDULER_MACHINE

# Install scheduler service
sudo cp /opt/workflow_app/jobs_manager/scripts/scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable scheduler
sudo systemctl start scheduler

# Check status
sudo systemctl status scheduler
```

---

## Notes

- Scheduler runs on dedicated instance using systemd service
- Use `scripts/deploy.sh` for automated deployments
