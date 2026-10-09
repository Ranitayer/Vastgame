#[tauri::command]
pub async fn browse_hosts(game_id: Option<String>) -> Result<serde_json::Value, String> {
    let game = game_id.unwrap_or_default();
    if !game.is_empty() && !crate::backend::valid_game_id(&game) {
        return Err("Invalid game ID.".into());
    }
    crate::backend::read(vec!["hosts".into(), "--json".into(), "--game".into(), game], "offers").await
}
