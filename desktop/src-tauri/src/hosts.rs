use std::process::Command;

#[tauri::command]
pub async fn browse_hosts() -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        #[cfg(target_os = "windows")]
        let mut command = {
            use std::os::windows::process::CommandExt;
            let mut cmd = Command::new("wsl.exe");
            cmd.args(["--distribution", "Vastgame", "--user", "vastgame", "--exec",
                "/home/vastgame/.local/bin/vastgame", "hosts", "--json"]);
            cmd.creation_flags(0x08000000);
            cmd
        };
        #[cfg(not(target_os = "windows"))]
        let mut command = {
            let home = std::env::var_os("HOME").ok_or("Cannot locate your Vastgame installation.")?;
            let home = std::path::PathBuf::from(home);
            let mut cmd = Command::new(home.join(".local/bin/vastgame"));
            let mut paths = vec![home.join(".local/bin")];
            if let Some(path) = std::env::var_os("PATH") { paths.extend(std::env::split_paths(&path)); }
            cmd.env("PATH", std::env::join_paths(paths).map_err(|_| "Cannot locate backend tools.")?);
            cmd.args(["hosts", "--json"]);
            cmd
        };
        let output = command.env("VASTAI_NO_UPDATE_CHECK", "1").output()
            .map_err(|_| "Install and configure the Vastgame backend before browsing hosts.")?;
        if !output.status.success() {
            return Err("Host search failed. Check your Vast account, selected game package and internet connection, then refresh.".into());
        }
        if output.stdout.len() > 8 * 1024 * 1024 {
            return Err("Host response is too large. Refresh to retry.".into());
        }
        let data: serde_json::Value = serde_json::from_slice(&output.stdout)
            .map_err(|_| "The backend returned invalid host data. Update the backend and retry.")?;
        if !data.get("offers").is_some_and(|offers| offers.is_array()) {
            return Err("The backend returned invalid host data.".into());
        }
        Ok(data)
    }).await.map_err(|_| "Host search could not finish.".to_string())?
}
