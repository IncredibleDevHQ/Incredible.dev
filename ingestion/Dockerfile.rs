# Use an official Rust image as a parent image
FROM rust:1.57

# Set the working directory in the container to /usr/src/myapp
WORKDIR /usr/src/myapp

# Copy the local Cargo.toml, Cargo.lock, and repo directory to the container
COPY Cargo.toml Cargo.lock ./
COPY repo ./repo

# Build dependencies, this will be cached until Cargo.toml changes
RUN cargo build --release

# Copy the content of your local src directory to the working directory
COPY src ./src

# Build the application
RUN cargo install --path .

# Specify the command to run on container start
CMD ["ingestion", "$REPO_SUBFOLDER", "$REPO_NAME"] # Make sure your Rust app handles this argument
