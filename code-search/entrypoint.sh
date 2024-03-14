#!/bin/sh
# entrypoint.sh

# Set the library path for shared libraries
export LD_LIBRARY_PATH=/usr/src/myapp/target/release:$LD_LIBRARY_PATH

# Download secrets and output to .env
# doppler secrets download --no-file --format env > .env

# Run the application
chmod +x target/release/semantic-search-rust
./target/release/semantic-search-rust
