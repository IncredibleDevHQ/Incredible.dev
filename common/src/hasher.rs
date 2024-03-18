use md5::compute;

pub fn generate_quikwit_index_name(namespace: &str) -> String {
    // let repo_name = namespace.split("/").last().unwrap();
    // let version = namespace.split("/").nth(0).unwrap();
    // let md5_index_id = compute(namespace);
    // // create a hex string
    // let new_index_id = format!("{:x}", md5_index_id);
    // let index_name = format!("{}-{}-{}", version, repo_name, new_index_id);
    return namespace.to_string(); 
}

pub fn generate_qdrant_index_name(namespace: &str) -> String {
    // let repo_name = namespace.split("/").last().unwrap();
    // let version = namespace.split("/").nth(0).unwrap();
    // let md5_index_id = compute(namespace);
    // // create a hex string
    // let new_index_id = format!("{:x}", md5_index_id);
    // let index_name = format!(
    //     "{}-{}-{}-documents-symbols",
    //     version, repo_name, new_index_id
    // );
    return namespace.to_string()
}
