#!/bin/bash

# The script expects the filename as the first argument
if [ -z "$1" ]; then
  echo "No filename provided. Usage: ./myscript.sh filename"
  exit 1
fi

# Replace 'yourkey.pem' with your actual pem file name if it's different
KEY_FILE="/Users/incredible/Downloads/keep_safe.pem"

# Ensure the .pem file has the right permissions
chmod 400 $KEY_FILE

# Replace with your actual user and host details
USER_HOST="ubuntu@ec2-3-110-166-19.ap-south-1.compute.amazonaws.com"

# The destination path on the remote server
DEST_PATH="/home/ubuntu"

# The source file to copy (passed as the first argument to the script)
SRC_FILE="$1"

# Now use scp to securely copy the file to the remote server
scp -i $KEY_FILE $SRC_FILE $USER_HOST:$DEST_PATH
