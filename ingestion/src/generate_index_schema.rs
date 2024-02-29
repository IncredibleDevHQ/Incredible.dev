// yaml_modifier.rs

use std::fs;
use std::io::{self, Read, Write};
use std::path::Path;

pub fn replace_index_id_in_yaml(
    mut yaml_content: String,
    new_index_id: &str,
) -> io::Result<String> {
    // Read the YAML file into a String
    // let mut yaml_content = String::new();
    // let mut file = fs::File::open(yaml_path)?;
    // file.read_to_string(&mut yaml_content)?;

    // Replace the index_id value
    let old_index_id_pattern = "index_id: ";
    if let Some(start) = yaml_content.find(old_index_id_pattern) {
        let end = yaml_content[start..]
            .find('\n')
            .unwrap_or(yaml_content.len());
        yaml_content.replace_range(
            start + old_index_id_pattern.len()..start + end,
            new_index_id,
        );
    }

    // Write the modified data back to the YAML file
    // let mut file = fs::File::create(yaml_path)?;
    // file.write_all(yaml_content.as_bytes())?;

    Ok(yaml_content)
}
