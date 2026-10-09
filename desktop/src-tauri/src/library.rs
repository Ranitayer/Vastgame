#[tauri::command]
pub async fn browse_library() -> Result<serde_json::Value, String> {
    crate::backend::read(vec!["list".into(), "--json".into()], "games").await
}

#[tauri::command]
pub async fn game_artwork(game_id: String, kind: String) -> Result<serde_json::Value, String> {
    if !crate::backend::valid_game_id(&game_id) || !matches!(kind.as_str(), "cover" | "banner") {
        return Err("Invalid artwork request.".into());
    }
    crate::backend::read(vec!["artwork".into(), "--game".into(), game_id, kind], "image").await
}

#[tauri::command]
pub async fn game_details(steam_appid: u32) -> Result<serde_json::Value, String> {
    if steam_appid == 0 { return Err("Invalid game details request.".into()); }
    crate::backend::read(vec!["details".into(), steam_appid.to_string()], "details").await
}
