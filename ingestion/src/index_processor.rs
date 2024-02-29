use anyhow::{anyhow, Result};
use futures::stream::StreamExt;
use itertools::Itertools;
use md5::compute;
use ort::error;
use std::process;

use std::error::Error;
use std::fs::{self};

use crate::FileFields;
use log::{debug, error, info};
use std::env;
use std::path::Path;

use crate::generate_index_schema;

use tokio::time::{sleep, Duration};

use reqwest::{self, StatusCode};

fn get_config_path() -> Option<String> {
    // Get the current executable path
    let exe_path = env::current_exe().ok()?;

    // Get the directory containing the executable
    let exe_dir = exe_path.parent()?;

    // Append "index-config.yaml" to the executable directory path
    let config_path = exe_dir.join("index-config.yaml");

    // Convert the path to a String if possible
    log::debug!("Config path: {:?}", config_path);
    config_path.to_str().map(|s| s.to_owned())
}

// Input is repo name in format v2/owner_name/repo_name.
// We generate hash of namespace using md5 and prefix it with the repo name extracted from namespace.
pub fn generate_quikwit_index_name(namespace: &str) -> String {
    let repo_name = namespace.split("/").last().unwrap();
    let version = namespace.split("/").nth(0).unwrap();
    let md5_index_id = compute(namespace);
    // create a hex string
    let new_index_id = format!("{:x}", md5_index_id);
    let index_name = format!("{}-{}-{}", version, repo_name, new_index_id);
    return index_name;
}

pub async fn process_entries(all_entries: Vec<FileFields>, repo_name: &str, quickwit_url: &str) {
    // config path is $pwd/index-config.yaml
    // let config_path = get_config_path().unwrap();
    // let path = Path::new(&config_path);

    let config = include_str!("../index-config.yaml");
    let new_index_id = generate_quikwit_index_name(repo_name);
    let index_config =
        generate_index_schema::replace_index_id_in_yaml(config.to_string(), &new_index_id).unwrap();

    debug!("Sending first yaml to server...");
    let response = send_yaml_to_server(&index_config, &quickwit_url, &new_index_id).await;
    match response {
        Ok(_) => {
            info!("Successfully sent yaml to server");
        }
        Err(e) => {
            error!("Failed to send yaml to server: {:?}", e);
        }
    }

    let entries = all_entries.clone();
    let iter = entries.iter();
    let chunks = iter.chunks(3);
    let all_entries_stream = futures::stream::iter(&chunks);

    // let all_entries_stream = futures::stream::iter(&entries.iter().chunks(3));

    all_entries_stream
        .for_each_concurrent(Some(1), |chunk| async {
            let url = format!(
                "{}/api/v1/{}/ingest?commit=force",
                quickwit_url, new_index_id
            );

            let json_data_vec: Result<Vec<String>, _> = chunk
                .into_iter()
                .map(|record| serde_json::to_string(record))
                .collect();

            match json_data_vec {
                Ok(data_vec) => {
                    let batch_data = data_vec.join("\n");
                    match send_content_to_server(&batch_data, &url).await {
                        Ok(response) => {
                            // Handle the response immediately if necessary.
                            debug!("Successfully sent data: {:?}", response);
                        }
                        Err(e) => {
                            error!("Repo ID: {}", repo_name);
                            error!("Failed to send data to quickwit, ending process: {:?}", e);
                            process::exit(1);
                        }
                    }
                }
                Err(e) => {
                    error!("Error serializing data: {:?}", e);
                }
            }
        })
        .await;
}

async fn send_yaml_to_server(
    config_yaml: &str,
    quickwit_url: &str,
    new_index_id: &str,
) -> anyhow::Result<()> {
    debug!("Reading YAML content...");

    let create_index_url = quickwit_url.to_owned() + "/api/v1/indexes";
    let describe_url = quickwit_url.to_owned() + "/api/v1/indexes/" + new_index_id + "/describe";
    let clear_url = quickwit_url.to_owned() + "/api/v1/indexes/" + new_index_id + "/clear";

    debug!("Making GET request to describe URL: {}", &describe_url);
    let client = reqwest::Client::new();
    let describe_response = client.get(&describe_url).send().await?;

    match describe_response.status() {
        StatusCode::NOT_FOUND => {
            // Index does not exist, proceed to create
            // add info log
            info!(
                "Index not found, creating new index at URL: {}",
                &create_index_url
            );

            let create_response = client
                .post(&create_index_url)
                .header("Content-Type", "application/yaml")
                .body(config_yaml.to_string())
                .send()
                .await?;

            if create_response.status() != StatusCode::OK {
                error!("Error creating index");
                return Err(anyhow::anyhow!("Error creating index"));
            }
        }
        StatusCode::OK => {
            // Index exists, proceed to clear
            info!("Index found, clearing index at URL: {}", &clear_url);
            debug!("Index found, clearing index at URL: {}", &clear_url);
            let clear_response = client.put(&clear_url).send().await?;

            if clear_response.status() != StatusCode::OK {
                error!("Error clearing index");
                return Err(anyhow::anyhow!("Error clearing index"));
            }
        }
        _ => {
            // Handle other unexpected statuses
            error!("Unexpected status code received from describe URL");
            return Err(anyhow::anyhow!(
                "Unexpected status code received from describe URL"
            ));
        }
    }

    // Add a delay of 10 seconds here
    sleep(Duration::from_secs(10)).await;

    let response_text = describe_response.text().await?;
    info!(
        "Response for describing/configuring quickwit: {}",
        response_text
    );

    Ok(())
}

async fn send_json_to_server(json_path: &str, url: &str) -> Result<(), Box<dyn Error>> {
    debug!("Reading JSON file...");

    // Read the JSON file content
    let json_content = fs::read_to_string(json_path)?;

    debug!("Making POST request...\n");
    debug!("{}", json_content);

    // Make the POST request
    let client = reqwest::Client::new();
    let response = client
        .post(url)
        .header("Content-Type", "application/json")
        .body(json_content)
        .send()
        .await?;

    // Print the response status and text
    info!("Status Json from quickit: {}", response.status());
    debug!("Response Json: {}", response.text().await?);

    fs::remove_file(json_path)?;

    Ok(())
}

async fn send_content_to_server(content: &str, url: &str) -> Result<()> {
    // Read the JSON file content
    let json_content = content.to_string();

    debug!("Making POST request to quickwit...\n to {}", url);

    // Make the POST request
    let client = reqwest::Client::new();
    let response = client
        .post(url)
        .header("Content-Type", "application/json")
        .body(json_content)
        .send()
        .await?;

    match response.status() {
        StatusCode::OK | StatusCode::CREATED | StatusCode::ACCEPTED => {
            info!("Status from quickwit: {}", response.status());
            debug!("Response from quickwit: {}", response.text().await?);
            Ok(())
        }
        _ => {
            let error_message = format!("Error response from quickwit: {}", response.status());
            error!("{}", &error_message);
            Err(anyhow::anyhow!(error_message))
        }
    }
}
