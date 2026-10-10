#[tauri::command]
pub async fn read_settings() -> Result<serde_json::Value, String> {
    crate::backend::read(vec!["desktop-settings".into()], "settings").await
}

#[tauri::command]
pub async fn reset_settings() -> Result<serde_json::Value, String> {
    crate::backend::read(vec!["desktop-settings".into(), "--reset".into()], "settings").await
}

#[tauri::command]
pub async fn sensitive_settings(action: String, events: tauri::ipc::Channel<serde_json::Value>) -> Result<(), String> {
    if !["force-stop", "delete-history"].contains(&action.as_str()) { return Err("Invalid sensitive action.".into()); }
    tauri::async_runtime::spawn_blocking(move || crate::launch::stream(vec!["desktop-sensitive".into(), action], events))
        .await.map_err(|_| "Sensitive action worker could not finish.".to_string())?
}

#[tauri::command]
pub async fn save_settings(patch: serde_json::Value) -> Result<serde_json::Value, String> {
    let valid = patch.as_object().is_some_and(|data| !data.is_empty() && data.len() <= 2 &&
        data.iter().all(|(key, value)| ["stream", "hosts"].contains(&key.as_str()) && value.is_object()));
    let payload = patch.to_string();
    if !valid || payload.len() > 65536 { return Err("Invalid settings request.".into()); }
    crate::backend::read(vec!["desktop-settings".into(), "--patch".into(), payload], "settings").await
}
