use std::fs;

use std::io::Read;

pub fn is_running_in_docker() -> bool {
    // Check for the Docker-specific file
    if fs::metadata("/.dockerenv").is_ok() {
        return true;
    }

    // Check for Docker signatures in /proc/1/cgroup
    let mut cgroup_content = String::new();
    if let Ok(mut file) = fs::File::open("/proc/1/cgroup") {
        if file.read_to_string(&mut cgroup_content).is_ok() {
            return cgroup_content.contains("docker") || cgroup_content.contains("kubepods");
        }
    }

    false
}
