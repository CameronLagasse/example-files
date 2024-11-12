#!/bin/bash

# Log file
#LOG_FILE="/home/cameron/backup_script.log"

# Define your directories
SOURCE_DIR="/nfs/seagate/"
DEST_DIR="/home/cameron/home-services/"

# Ensure the log file is writable by root (or the executing user)
#touch $LOG_FILE
#chmod 664 $LOG_FILE

# Copy non-hidden files excluding those that are log or db files and anything in "blobs" folders
rsync -av --delete --exclude '*.log' --exclude '*.db' --exclude '.*' --exclude 'blobs/**' $SOURCE_DIR/ $DEST_DIR/

# Set the right permissions for the copied files and the destination directory
chown -R cameron:cameron $DEST_DIR #>> $LOG_FILE 2>&1

# Perform Git operations as the cameron user
sudo -u cameron bash -c 'cd /home/cameron/ && /home/cameron/git_backup.sh' #>> $LOG_FILE 2>&1
