use lazy_static::lazy_static;
use std::sync::{Arc, Mutex};
use crate::ai_gateway::tiktoken::{CoreBPE, cl100k_base};
use sha2::Sha256;
use std::env;

/// Count how many tokens a piece of text needs to consume
pub fn count_tokens(text: &str) -> usize {
    cl100k_base_singleton()
        .lock()
        .encode_with_special_tokens(text)
        .len()
}

pub fn cl100k_base_singleton() -> Arc<Mutex<CoreBPE>> {
    lazy_static! {
        static ref CL100K_BASE: Arc<Mutex<CoreBPE>> = Arc::new(Mutex::new(cl100k_base().unwrap()));
    }
    CL100K_BASE.clone()
}

pub fn detect_os() -> String {
    let os = env::consts::OS;
    if os == "linux" {
        if let Ok(contents) = std::fs::read_to_string("/etc/os-release") {
            for line in contents.lines() {
                if let Some(id) = line.strip_prefix("ID=") {
                    return format!("{os}/{id}");
                }
            }
        }
    }
    os.to_string()
}

pub fn sha256sum(input: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(input);
    let result = hasher.finalize();
    format!("{:x}", result)
}

pub fn detect_shell() -> (String, String, &'static str) {
    let os = env::consts::OS;
    if os == "windows" {
        if env::var("NU_VERSION").is_ok() {
            ("nushell".into(), "nu.exe".into(), "-c")
        } else if let Some(ret) = env::var("PSModulePath").ok().and_then(|v| {
            let v = v.to_lowercase();
            if v.split(';').count() >= 3 {
                if v.contains("powershell\\7\\") {
                    Some(("pwsh".into(), "pwsh.exe".into(), "-c"))
                } else {
                    Some(("powershell".into(), "powershell.exe".into(), "-Command"))
                }
            } else {
                None
            }
        }) {
            ret
        } else {
            ("cmd".into(), "cmd.exe".into(), "/C")
        }
    } else if env::var("NU_VERSION").is_ok() {
        ("nushell".into(), "nu".into(), "-c")
    } else {
        let shell_cmd = env::var("SHELL").unwrap_or_else(|_| "/bin/sh".to_string());
        let shell_name = match shell_cmd.rsplit_once('/') {
            Some((_, name)) => name.to_string(),
            None => shell_cmd.clone(),
        };
        let shell_name = if shell_name == "nu" {
            "nushell".into()
        } else {
            shell_name
        };
        (shell_name, shell_cmd, "-c")
    }
}
