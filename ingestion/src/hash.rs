use blake3::Hasher;
use std::path::PathBuf;

pub fn compute_hashes(relative_path: PathBuf, buffer: &str, branch_list: &str) -> (String, String) {
    // Create the semantic hash
    let semantic_hash = {
        let mut hash = Hasher::new();
        //hash.update(crate::state::SCHEMA_VERSION.as_bytes());
        hash.update(relative_path.to_string_lossy().as_bytes()); // Convert to byte slice
        hash.update(buffer.as_bytes());
        hash.finalize().to_hex().to_string()
    };

    // Create the tantivy hash
    let tantivy_hash = {
        let mut hash = Hasher::new();
        hash.update(semantic_hash.as_ref());
        hash.update(branch_list.as_bytes());
        hash.finalize().to_hex().to_string()
    };

    (semantic_hash, tantivy_hash)
}

#[cfg(test)]
mod tests {
    use super::compute_hashes;
    use std::path::PathBuf;

    #[test]
    fn test_compute_hashes() {
        let relative_path = PathBuf::from("path/to/file");
        let buffer = "file content";
        let branch_list = "main";

        let (semantic_hash, tantivy_hash) = compute_hashes(relative_path, buffer, branch_list);

        // You should replace these with the expected values for the given input.
        let expected_semantic_hash =
            "af96123d76fe50cbec2197da801b4dc1042e285c748d6123ae72fb1063c87012";
        let expected_tantivy_hash =
            "3f516c5d06e5c298ad47cfdf3a2374997124541fb4f16971687abe54625eb05e";

        assert_eq!(semantic_hash, expected_semantic_hash);
        assert_eq!(tantivy_hash, expected_tantivy_hash);
    }
}
