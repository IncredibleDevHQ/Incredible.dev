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

# The source path and file on the remote server (passed as the first argument to the script)
SRC_PATH="/home/ubuntu/$1"

# The destination for the file on the local machine
DEST_PATH="."

# Now use scp to securely copy the file from the remote server to the local machine
scp -i $KEY_FILE $USER_HOST:$SRC_PATH $DEST_PATH
