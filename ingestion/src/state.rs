use core::fmt;
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

struct ProcessState {
    progress: u32,
    task_status: CodeIndexingTaskStatus,
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
lazy_static! {
    static ref GLOBAL_STATE: Mutex<HashMap<String, Arc<Mutex<ProcessState>>>> =
        Mutex::new(HashMap::new());
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
    let process_state = global_state
        .entry(process_id.to_string())
        .or_insert_with(|| {
            Arc::new(Mutex::new(ProcessState {
                progress: 0,
                task_status: CodeIndexingTaskStatus::Queued,
            }))
        });
    let mut state = process_state.lock().unwrap();
    state.progress = progress;
    state.task_status = task_status;
}

// Function to get the progress and status of a process
pub fn get_process_state(process_id: &str) -> Option<(u32, CodeIndexingTaskStatus)> {
    let global_state = GLOBAL_STATE.lock().unwrap();
    global_state.get(process_id).map(|state| {
        let state = state.lock().unwrap();
        (state.progress, state.task_status.clone())
    })
}
