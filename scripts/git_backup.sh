#!/bin/bash

# Log file
LOG_FILE="/home/cameron/git_backup.log"

# Start SSH agent and add key (not needed for HTTPS)
#eval "$(ssh-agent -s)" >> $LOG_FILE 2>&1
#ssh-add ~/.ssh/id_rsa >> $LOG_FILE 2>&1

# Navigate to the repository
cd /home/cameron/home-services/ #>> $LOG_FILE 2>&1

# Perform Git operations
git pull
git add .                               #>> $LOG_FILE 2>&1
git commit -m "Daily backup on $(date)" #>> $LOG_FILE 2>&1
git push origin main                    #>> $LOG_FILE 2>&1
echo "Backup to Git repo completed on $(date)" >>$LOG_FILE 2>&1
