use once_cell::sync::Lazy;
use regex::Regex;
use smallvec::SmallVec;
use std::collections::HashMap;
use std::path::Path;

pub fn index_filter<P: AsRef<Path>>(p: &P) -> bool {
    let path = p.as_ref();

    // Checking for .git components within the path.
    // Example: if the path contains ".git", the function returns false
    if path.components().any(|c| c.as_os_str() == ".git") {
        return false;
    }

    // List of blacklisted extensions
    #[rustfmt::skip]
    const EXT_BLACKLIST: &[&str] = &[
        // graphics
        "png", "jpg", "jpeg", "ico", "bmp", "bpg", "eps", "pcx", "ppm", "tga", "tiff", "wmf", "xpm",
        "svg",
        // fonts
        "ttf", "woff2", "fnt", "fon", "otf",
        // documents
        "pdf", "ps", "doc", "dot", "docx", "dotx", "xls", "xlsx", "xlt", "odt", "ott", "ods", "ots", "dvi", "pcl",
        // media
        "mp3", "ogg", "ac3", "aac", "mod", "mp4", "mkv", "avi", "m4v", "mov", "flv",
        // compiled
        "jar", "pyc", "war", "ear",
        // compression
        "tar", "gz", "bz2", "xz", "7z", "bin", "apk", "deb", "rpm",
        // executable
        "com", "exe", "out", "coff", "obj", "dll", "app", "class",
        // misc.
        "log", "wad", "bsp", "bak", "sav", "dat", "lock","map"

    ];

    // Checking if the path has an extension, and returning true if it doesn't.
    // Example: if the path is "folder/", it doesn't have an extension, so the function returns true
    let ext = match path.extension() {
        Some(ext) => ext.to_string_lossy(),
        None => return true,
    };

    // Checking if the extension is in the blacklist, returning false if it is.
    // Example: if the extension is "exe", which is in the blacklist, the function returns false
    if EXT_BLACKLIST.contains(&&*ext) {
        return false;
    }

    // Defining vendor patterns to match against the file path.
    static VENDOR_PATTERNS: Lazy<HashMap<&'static str, SmallVec<[Regex; 1]>>> = Lazy::new(|| {
        let patterns: &[(&[&str], &[&str])] = &[
            // Sample patterns for "go" and "proto"
            (
                &["go", "proto"],
                &["^(vendor|third_party)/.*\\.\\w+$", "\\w+\\.pb\\.go$"],
            ),
            // Sample patterns for web files
            (
                &["js", "jsx", "ts", "tsx", "css", "md", "json", "txt", "conf"],
                &["^(node_modules|vendor|dist)/.*\\.\\w+$"],
            ),
        ];
        patterns
            // Step 1: Flattening the Extensions and Patterns
            // This part takes each tuple of extensions and regex patterns
            // and maps each extension to its associated regex patterns.
            .iter()
            .flat_map(|(exts, rxs)| {
                exts.iter().map(move |&e| (e, rxs))
                // Example Input: &[(&["go", "proto"], &["vendor_regex1", "vendor_regex2"]), (&["js", "css"], &["web_regex"])]
                // Intermediate Output: [("go", &["vendor_regex1", "vendor_regex2"]), ("proto", &["vendor_regex1", "vendor_regex2"]), ("js", &["web_regex"]), ("css", &["web_regex"])]
            })
            // Step 2: Mapping Extensions to Regex
            // This map call is used to associate each extension with compiled regular expressions.
            .map(|(ext, rxs)| {
                // Step 3: Filtering and Compiling Regex
                // For each extension and its associated regex patterns, filter_map compiles the regex patterns
                // and filters out any that fail to compile.
                let regexes = rxs
                    .iter()
                    .filter_map(|source| match Regex::new(source) {
                        Ok(r) => Some(r), // Compiled successfully, include in the result.
                        Err(e) => {
                            println!("failed to compile vendor regex {:?}: {}", source, e); // Compilation failed, print an error message.
                            None // Exclude from the result.
                        }
                    })
                    // Step 4: Collecting the Result
                    // The successfully compiled regular expressions are collected into a container.
                    .collect();

                // Continuing the above example:
                // - For "go" extension: [compiled_vendor_regex1]
                // - For "js" extension: [compiled_web_regex]

                (ext, regexes) // Final Output: Mapping each extension to its corresponding compiled regular expressions.
            })
            // ...
            .collect()
    });

    // Checks if the extension has a corresponding regex pattern in the VENDOR_PATTERNS,
    // and checks if the path matches any of these patterns.
    // Example: if the extension is "go" and the path is "vendor/library.go", the function returns false
    match VENDOR_PATTERNS.get(&*ext) {
        None => true,
        Some(rxs) => !rxs.iter().any(|r| r.is_match(&path.to_string_lossy())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_index_filter() {
        let test_cases = [
            // Format: (input_path, expected_result)
            ("", true),
            ("fonts/test.ttf", false),
            ("media/test.mp3", false),
            ("compressed/test.tar", false),
            ("executables/test.exe", false),
            ("logs/test.log", false),
            ("third_party/my_package.pb.go", false),
            ("dist/style.css", false),
            ("vendor/script.jsx", false),
            ("node_modules/library.json", false),
            ("vendor/config.conf", false),
            ("src/main.rs", true),
            ("scripts/test.py", true),
            ("templates/index.html", true),
            ("assets/style.scss", true),
            ("data/input.xml", true),
            (".git/validfile.rs", false),
            ("vendor/validfile.rs", true),
            ("valid_dir/validfile.jpg", false),
            ("valid_dir/.git", false),
            ("valid_dir/validfile.rs", true),
            ("path/with/.git/inside", false),
            ("path/with.git/inside", true),
            ("path/with/some_exe.com", false),
            (".github/workflows//dependencies.yml", false),
            // TODO: Directories and some files inside node_modules still gets read, take a look at it later.
            // commenting the test case for now.
            ("node_modules/undefsafe/workflows", false),
        ];

        for (path_str, expected_result) in &test_cases {
            let path = Path::new(path_str);
            let actual_result = index_filter(&path);
            assert_eq!(
                actual_result, *expected_result,
                "Test failed for path: {}. Expected: {}, but got: {}",
                path_str, expected_result, actual_result
            );
        }
    }
}
