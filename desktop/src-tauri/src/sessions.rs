use serde_json::Value;

fn validate_id(session_id: &str) -> Result<(), String> {
    let digits = session_id.strip_prefix("vastgame-").unwrap_or("");
    if digits.is_empty() || digits.len() > 24 || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err("Invalid session identity.".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn session_logs(session_id: String, cursor: u64) -> Result<Value, String> {
    read_archive(session_id, cursor, false).await
}

#[tauri::command]
pub async fn session_events(session_id: String, cursor: u64) -> Result<Value, String> {
    read_archive(session_id, cursor, true).await
}

async fn read_archive(session_id: String, cursor: u64, events: bool) -> Result<Value, String> {
    validate_id(&session_id)?;
    if cursor > 1024 * 1024 * 1024 { return Err("Session log cursor exceeds the read limit.".into()); }
    crate::backend::read(vec!["sessions".into(), if events { "event-page".into() } else { "log-page".into() }, session_id, "--json".into(), "--limit".into(), "200".into(), "--cursor".into(), cursor.to_string()], "entries").await
}

#[tauri::command]
pub async fn browse_sessions(offset: u32, refresh_billing: bool, days: u16, status: String, order: String) -> Result<Value, String> {
    if ![0, 1, 3, 7, 30, 365].contains(&days) ||
        !["All", "Starting", "Running", "Failed", "Retained", "Shutdown"].contains(&status.as_str()) ||
        !["newest", "oldest", "highest-cost", "lowest-cost", "longest-time", "shortest-time"].contains(&order.as_str()) {
        return Err("Invalid session filters.".into());
    }
    let mut args = vec!["sessions".into(), "--json".into(), "--limit".into(), "48".into(), "--offset".into(), offset.to_string()];
    args.extend(["--days".into(), days.to_string(), "--status".into(), status, "--sort".into(), order]);
    if refresh_billing { args.push("--refresh-billing".into()); }
    crate::backend::read(args, "sessions").await
}

#[tauri::command]
pub async fn prepare_session(session_id: String, shutdown: bool) -> Result<Value, String> {
    validate_id(&session_id)?;
    let mut args = vec!["desktop-history-prepare".into(), session_id];
    if shutdown { args.push("--shutdown".into()); }
    crate::backend::read(args, "session").await
}
