// NeuralCut Tauri 2 shell — Phase 1 development skeleton.
//
// The shell starts the local Python backend as a child process and points the
// main window at http://127.0.0.1:8765. This assumes a development checkout
// with Python able to import the `neuralcut` package (for example after
// running scripts/setup.ps1 and setting NEURALCUT_PYTHON to .venv's python).
//
// A distributable Windows installer that bundles/freeze the backend is
// Phase 7 work; see docs/ROADMAP.md and docs/KNOWN_ISSUES.md. This shell has
// not been compiled in the Linux foundation environment because Rust and the
// Windows WebView2 toolchain were unavailable there.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    process::{Child, Command},
    sync::Mutex,
};

static BACKEND: Mutex<Option<Child>> = Mutex::new(None);

fn python_executable() -> String {
    if let Ok(path) = std::env::var("NEURALCUT_PYTHON") {
        if !path.trim().is_empty() {
            return path;
        }
    }

    #[cfg(windows)]
    {
        "python".to_string()
    }

    #[cfg(not(windows))]
    {
        "python3".to_string()
    }
}

fn start_backend() -> std::io::Result<Child> {
    Command::new(python_executable())
        .args([
            "-m",
            "neuralcut",
            "--no-browser",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ])
        .spawn()
}

fn stop_backend() {
    if let Ok(mut guard) = BACKEND.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|_app| {
            let child = start_backend().expect(
                "failed to start NeuralCut Python backend; set NEURALCUT_PYTHON to the .venv python executable",
            );
            if let Ok(mut guard) = BACKEND.lock() {
                *guard = Some(child);
            }
            Ok(())
        })
        .on_window_event(|_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_backend();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running NeuralCut Tauri shell");
}
