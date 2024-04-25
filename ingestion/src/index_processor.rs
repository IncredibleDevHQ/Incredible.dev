use crate::config::{get_quickwit_url, get_yaml_config_path};
use crate::FileFields;
use anyhow::{anyhow, Result};
use futures::stream::StreamExt;
use itertools::Itertools;
use std::error::Error;
use std::fs::{self, File};
use std::io::Write;
use std::path::Path;

use crate::generate_index_schema;

pub async fn process_entries(all_entries: Vec<FileFields>, repo_name: &str) {
    // println!("creating yaml schema");
    // read yaml config path from env
    let yaml_config_path = get_yaml_config_path();
    let path = Path::new(&yaml_config_path);
    generate_index_schema::replace_index_id_in_yaml(path, repo_name);
    let quickwit_url = get_quickwit_url();
    let url = &format!("{}/api/v1/indexes", &quickwit_url);

    log::debug!("Sending first yaml to server...");
    let response = send_yaml_to_server(&get_yaml_config_path(), url).await;
    match response {
        Ok(_) => {
            log::info!("Successfully sent yaml to server");
        }
        Err(e) => {
            log::error!("Failed to send yaml to server: Aborting {:?}", e);
        }
    }
    // println!("out");
    let entries = all_entries.clone();
    let iter = entries.iter();
    let chunks = iter.chunks(3);
    let all_entries_stream = futures::stream::iter(&chunks);

    // let all_entries_stream = futures::stream::iter(&entries.iter().chunks(3));

    all_entries_stream
        .for_each_concurrent(Some(10), |chunk| async {
            let url = format!(
                "{}/api/v1/{}/ingest?commit=force",
                &quickwit_url, &repo_name
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
                            println!("Successfully sent data: {:?}", response);
                        }
                        Err(e) => {
                            println!("Failed to send data: {:?}", e);
                        }
                    }
                }
                Err(e) => {
                    println!("Error serializing data: {:?}", e);
                }
            }
        })
        .await;
}

async fn send_yaml_to_server(yaml_path: &str, url: &str) -> anyhow::Result<()> {
    println!("Reading YAML file...");
    // Read the YAML file content
    let yaml_content = fs::read_to_string(yaml_path)?;

    println!("Making POST request...");
    // Make the POST request
    let client = reqwest::Client::new();
    let response = client
        .post(url)
        .header("Content-Type", "application/yaml")
        .body(yaml_content)
        .send()
        .await?;

    // Print the response status and text
    println!("Status Yaml: {}", response.status());
    // println!("Response Yaml: {}", response.text().await?);

    // return error if status is not 200
    if response.status() != 200 {
        return Err(anyhow!("Error sending yaml to server"));
    }
    Ok(())
}

async fn send_json_to_server(json_path: &str, url: &str) -> Result<(), Box<dyn Error>> {
    println!("Reading JSON file...");

    // Read the JSON file content
    let json_content = fs::read_to_string(json_path)?;

    println!("Making POST request...\n");
    println!("{}", json_content);

    // Make the POST request
    let client = reqwest::Client::new();
    let response = client
        .post(url)
        .header("Content-Type", "application/json")
        .body(json_content)
        .send()
        .await?;

    // Print the response status and text
    println!("Status Json: {}", response.status());
    println!("Response Json: {}", response.text().await?);

    fs::remove_file(json_path)?;

    Ok(())
}

async fn send_content_to_server(content: &str, url: &str) -> Result<()> {
    // Read the JSON file content
    let json_content = content.to_string();

    println!("Making POST request...\n");

    // Make the POST request
    let client = reqwest::Client::new();
    let response = client
        .post(url)
        .header("Content-Type", "application/json")
        .body(json_content)
        .send()
        .await?;

    // Print the response status and text
    println!("Status Json: {}", response.status());
    println!("Response Json: {}", response.text().await?);

    Ok(())
}
