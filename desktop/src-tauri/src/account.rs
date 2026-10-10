#[tauri::command]
pub async fn account_balance() -> Result<serde_json::Value, String> {
    crate::backend::read(vec!["balance".into(), "--json".into()], "balance").await
}
