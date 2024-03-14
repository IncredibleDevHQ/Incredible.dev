# Use an official Rust image as a parent image
FROM rust:1.73.0-bullseye

# Set the working directory in the container to /usr/src/myapp
WORKDIR /usr/src/myapp

# Copy the local Cargo.toml, Cargo.lock, and repo directory to the container
COPY Cargo.toml Cargo.lock ./
COPY model ./model 

# Copy the content of your local src directory to the working directory
COPY src ./src

# Setup Doppler
# ARG DOPPLER_AUTH_TOKEN
# ARG DOPPLER_CONFIG
# ENV DOPPLER_TOKEN ${DOPPLER_AUTH_TOKEN}
# ENV DOPPLER_CONFIG ${DOPPLER_CONFIG}

# RUN apt-get update && apt-get install -y apt-transport-https ca-certificates curl gnupg && \
#     curl -sLf --retry 3 --tlsv1.2 --proto "=https" 'https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key' | gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg && \
#     echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" | tee /etc/apt/sources.list.d/doppler-cli.list && \
#     apt-get update && \
#     apt-get -y install doppler

# RUN doppler setup -p semantic-search-rust --config $DOPPLER_CONFIG

# Expose 3003 to the outside world
EXPOSE 3003

# Copy the entrypoint script into a global path and make it executable
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Build the application
RUN cargo build --release

# Specify the command to run on container start
CMD ["/usr/local/bin/entrypoint.sh"]
