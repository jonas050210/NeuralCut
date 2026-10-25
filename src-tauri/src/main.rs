// NeuralCut Tauri 2 shell.
//
// Starts the Python backend as a child process on a free loopback port and
// points the main window at it. Backend resolution order:
//
//   1. $NEURALCUT_BACKEND_EXE          (explicit override)
//   2. neuralcut-backend[.exe] next to the shell executable (packaged
//      PyInstaller sidecar, see scripts/build_backend.ps1)
//   3. $NEURALCUT_PYTHON / python[3] -m neuralcut (development checkout;
//      set NEURALCUT_BACKEND_DIR to the checkout root in that case)
//
// If a sibling ffmpeg[.exe] exists (packaged builds), it is handed to the
// backend via NEURALCUT_MEDIA__FFMPEG_PATH. The backend child is killed
// when the shell exits. This file has NOT been compiled in the Linux
// development sandbox (no Rust toolchain there); it must be built and
// verified on Windows -- see docs/PACKAGING.md.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    io,
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command},
    sync::Mutex,
    time::{Duration, Instant},
};

static BACKEND: Mutex<Option<Child>> = Mutex::new(None);

fn free_port() -> io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn sibling(name: &str) -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let candidate = exe.parent()?.join(name);
    candidate.is_file().then_some(candidate)
}

fn backend_command(port: u16) -> Command {
    let mut cmd;
    if let Ok(exe) = std::env::var("NEURALCUT_BACKEND_EXE") {
        if !exe.trim().is_empty() {
            cmd = Command::new(exe);
            cmd.args(["--no-browser"]);
            return with_common_args(cmd, port);
        }
    }
    #[cfg(windows)]
    let sidecar = "neuralcut-backend.exe";
    #[cfg(not(windows))]
    let sidecar = "neuralcut-backend";
    if let Some(path) = sibling(sidecar) {
        cmd = Command::new(path);
        cmd.args(["--no-browser"]);
        return with_common_args(cmd, port);
    }
    // Development fallback: python -m neuralcut from the checkout root.
    let python = std::env::var("NEURALCUT_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) { "python".into() } else { "python3".into() }
    });
    cmd = Command::new(python);
    cmd.args(["-m", "neuralcut", "--no-browser"]);
    if let Ok(dir) = std::env::var("NEURALCUT_BACKEND_DIR") {
        cmd.current_dir(dir);
    } else if let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
    {
        cmd.current_dir(exe_dir);
    }
    with_common_args(cmd, port)
}

fn with_common_args(mut cmd: Command, port: u16) -> Command {
    cmd.args(["--host", "127.0.0.1", "--port", &port.to_string()]);
    #[cfg(windows)]
    let ffmpeg = "ffmpeg.exe";
    #[cfg(not(windows))]
    let ffmpeg = "ffmpeg";
    if let Some(ffmpeg_path) = sibling(ffmpeg) {
        cmd.env("NEURALCUT_MEDIA__FFMPEG_PATH", ffmpeg_path);
    }
    cmd
}

fn wait_until_listening(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
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
    let port = free_port().expect("could not allocate a free local port");
    tauri::Builder::default()
        .setup(move |app| {
            let mut child = backend_command(port).spawn().map_err(|e| {
                Box::<dyn std::error::Error>::from(format!(
                    "failed to start NeuralCut backend: {e}. Packaged builds need the \
                     neuralcut-backend sidecar; development checkouts need NEURALCUT_PYTHON \
                     (and NEURALCUT_BACKEND_DIR) set. See docs/PACKAGING.md."
                ))
            })?;
            if !wait_until_listening(port, Duration::from_secs(20)) {
                let _ = child.kill();
                return Err(Box::<dyn std::error::Error>::from(
                    "NeuralCut backend did not start listening within 20s; \
                     check the backend log in the app data directory.",
                ));
            }
            if let Ok(mut guard) = BACKEND.lock() {
                *guard = Some(child);
            }
            let url = format!("http://127.0.0.1:{port}/");
            tauri::WebviewWindowBuilder::new(
                app.handle(),
                "main",
                tauri::WebviewUrl::External(url.parse().expect("valid backend URL")),
            )
            .title("NeuralCut")
            .inner_size(1280.0, 800.0)
            .min_inner_size(960.0, 600.0)
            .resizable(true)
            .build()?;
            Ok(())
        })
        .on_window_event(|_window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_backend();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running NeuralCut Tauri shell");
    stop_backend();
}
