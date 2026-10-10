use std::{io::{BufRead, BufReader}, process::Stdio, sync::{Arc, Mutex}};
use tauri::ipc::Channel;
use serde_json::Value;

#[derive(Default)]
pub struct LaunchState(pub Arc<Mutex<bool>>);

fn identity(job: &str) -> bool {
    job.len() == 32 && job.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}

pub(crate) fn stream(args: Vec<String>, events: Channel<Value>) -> Result<(), String> {
    let mut command = crate::backend::command(&args, false)?;
    let mut child = command.env("PYTHONUNBUFFERED", "1").stdin(Stdio::null())
        .stdout(Stdio::piped()).stderr(Stdio::null()).spawn()
        .map_err(|_| "Cannot start the installed Vastgame backend.".to_string())?;
    let output = child.stdout.take().ok_or("Launch output unavailable.")?;
    let mut finished = false;
    let mut reader = BufReader::new(output);
    let mut line = Vec::new();
    let mut oversized = false;
    loop {
        let buffer = reader.fill_buf().map_err(|_| "Launch output interrupted.")?;
        if buffer.is_empty() {
            if !line.is_empty() && !oversized { send_line(&line, &events, &mut finished); }
            break;
        }
        let newline = buffer.iter().position(|byte| *byte == b'\n');
        let count = newline.map_or(buffer.len(), |index| index + 1);
        if !oversized && line.len() + count <= 16384 { line.extend_from_slice(&buffer[..count]); }
        else { oversized = true; line.clear(); }
        reader.consume(count);
        if newline.is_some() {
            if !oversized { send_line(&line, &events, &mut finished); }
            line.clear(); oversized = false;
        }
    }
    let _ = child.wait();
    if !finished { return Err("Backend ended before reporting completion. Check Vastgame status; any VM was retained.".into()); }
    Ok(())
}

fn send_line(line: &[u8], events: &Channel<Value>, finished: &mut bool) {
    if let Ok(event) = serde_json::from_slice::<Value>(line) {
        if event.get("type").and_then(Value::as_str) == Some("finished") { *finished = true; }
        let _ = events.send(event);
    }
}

#[tauri::command]
pub async fn launch_game(game_id: String, offer_id: u64, machine_id: u64, max_price: f64, job_id: String,
    started_at: Option<u64>, events: Channel<Value>, state: tauri::State<'_, LaunchState>) -> Result<(), String> {
    if !identity(&job_id) || !crate::backend::valid_game_id(&game_id) ||
        offer_id == 0 || !max_price.is_finite() || max_price < 0.0 {
        return Err("Invalid game or rig selection.".into());
    }
    let busy = state.inner().0.clone();
    { let mut active = busy.lock().map_err(|_| "Launch state unavailable.")?;
      if *active { return Err("A launch is already active. Check its logs.".into()); }
      *active = true;
    }
    let result = tauri::async_runtime::spawn_blocking(move || {
        let mut args = vec!["desktop-launch".into(), job_id, game_id, offer_id.to_string(), max_price.to_string(), machine_id.to_string()];
        if let Some(started) = started_at { args.push(started.to_string()); }
        stream(args, events)
    }).await;
    if let Ok(mut active) = busy.lock() { *active = false; }
    result.map_err(|_| "Launch worker could not finish.".to_string())?
}

#[tauri::command]
pub async fn connect_game(job_id: String, events: Channel<Value>, state: tauri::State<'_, LaunchState>) -> Result<(), String> {
    if !identity(&job_id) { return Err("Invalid launch identity.".into()); }
    let busy = state.inner().0.clone();
    { let mut active = busy.lock().map_err(|_| "Launch state unavailable.")?;
      if *active { return Err("Another rig operation is active. Check its logs.".into()); }
      *active = true;
    }
    let result = tauri::async_runtime::spawn_blocking(move || stream(vec!["desktop-connect".into(), job_id], events)).await;
    if let Ok(mut active) = busy.lock() { *active = false; }
    result.map_err(|_| "Connection worker could not finish.".to_string())?
}

#[tauri::command]
pub async fn shutdown_game(job_id: String, force: bool, events: Channel<Value>) -> Result<(), String> {
    if !identity(&job_id) { return Err("Invalid launch identity.".into()); }
    let mut args = vec!["desktop-shutdown".into(), job_id];
    if force { args.push("--force".into()); }
    tauri::async_runtime::spawn_blocking(move || stream(args, events))
        .await.map_err(|_| "Shutdown worker could not finish.".to_string())?
}

#[tauri::command]
pub async fn quote_game(game_id: String, offer_id: u64, machine_id: u64) -> Result<Value, String> {
    if offer_id == 0 || !crate::backend::valid_game_id(&game_id) {
        return Err("Invalid game or rig selection.".into());
    }
    crate::backend::read(vec!["quote".into(), game_id, offer_id.to_string(), machine_id.to_string()], "quote").await
}

#[tauri::command]
pub async fn current_launch(job_id: Option<String>) -> Result<Value, String> {
    let mut args = vec!["desktop-session".into()];
    if let Some(job) = job_id {
        if !identity(&job) { return Err("Invalid launch identity.".into()); }
        args.push(job);
    }
    crate::backend::read(args, "session").await
}

#[tauri::command]
pub async fn follow_launch(job_id: String, events: Channel<Value>) -> Result<(), String> {
    if !identity(&job_id) { return Err("Invalid launch identity.".into()); }
    tauri::async_runtime::spawn_blocking(move || stream(vec!["desktop-watch".into(), job_id], events))
        .await.map_err(|_| "Progress watcher could not finish.".to_string())?
}
