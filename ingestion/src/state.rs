use core::fmt;
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

#[derive(Clone)]
pub struct ProcessState {
    pub repo_name: String,
    pub repo_path: String,
    pub progress: u32,
    pub task_status: CodeIndexingTaskStatus,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub enum CodeIndexingTaskStatus {
    Queued,
    Running,
    Completed,
    Failed,
}

impl fmt::Display for CodeIndexingTaskStatus {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            CodeIndexingTaskStatus::Queued => write!(f, "Queued"),
            CodeIndexingTaskStatus::Running => write!(f, "Running"),
            CodeIndexingTaskStatus::Completed => write!(f, "Completed"),
            CodeIndexingTaskStatus::Failed => write!(f, "Failed"),
        }
    }
}

// Define the global state structure
// TODO: Eventually rework this to use crossbeam instead of lazy_static to better manage the progress
// updates in concurrent enviroments. Also look into storing these states in a database rather than in-memory.
lazy_static! {
    static ref GLOBAL_STATE: Mutex<HashMap<String, Arc<Mutex<ProcessState>>>> =
        Mutex::new(HashMap::new());
}

// Function to queue a new process
pub fn queue_process(process_id: &str, repo_name: &str, repo_path: &str) {
    log::info!("Queueing process {} for repo {}", process_id, repo_name);
    let mut global_state = GLOBAL_STATE.lock().unwrap();
    global_state.insert(
        process_id.to_string(),
        Arc::new(Mutex::new(ProcessState {
            repo_name: repo_name.to_string(),
            repo_path: repo_path.to_string(),
            progress: 0,
            task_status: CodeIndexingTaskStatus::Queued,
        })),
    );
}

// Function to update a process state with progress and status
pub fn update_process_state(process_id: &str, progress: u32, task_status: CodeIndexingTaskStatus) {
    log::info!(
        "Updating process state for process id: {} with {}, {}",
        process_id,
        progress,
        task_status
    );
    let mut global_state = GLOBAL_STATE.lock().unwrap();
    match global_state.get_mut(process_id) {
        Some(state) => {
            let mut state = state.lock().unwrap();
            state.progress = progress;
            state.task_status = task_status;
        }
        None => {
            log::error!("Process {} not found in global state", process_id);
        }
    }
}

// Function to get the progress and status of a process
pub fn get_process_state(process_id: &str) -> Option<ProcessState> {
    let global_state = GLOBAL_STATE.lock().unwrap();
    if let Some(state_arc) = global_state.get(process_id) {
        let state = state_arc.lock().unwrap();
        Some(state.clone())
    } else {
        None
    }
}
