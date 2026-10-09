use std::{io::Read, process::{Command, Stdio}, sync::mpsc, time::{Duration, Instant}};

pub fn valid_game_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 64 &&
        id.bytes().next().is_some_and(|b| b.is_ascii_lowercase() || b.is_ascii_digit()) &&
        id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"._-".contains(&b))
}

fn stop_read(child: &mut std::process::Child) {
    // Read requests own an isolated process group, never a rental lifecycle.
    #[cfg(unix)]
    { let _ = Command::new("/bin/kill").args(["-KILL", "--", &format!("-{}", child.id())]).status(); }
    let _ = child.kill();
    let _ = child.wait();
}

pub async fn read(args: Vec<String>, collection: &'static str) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut child = command(&args, true)?.env("VASTAI_NO_UPDATE_CHECK", "1")
            .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()
            .map_err(|_| "Cannot start Vastgame. Install/configure its Linux or WSL backend.".to_string())?;
        let (send, receive) = mpsc::channel();
        for (is_stdout, pipe, limit) in [
            (true, Box::new(child.stdout.take().ok_or("Backend output missing.")?) as Box<dyn Read + Send>, 8 * 1024 * 1024),
            (false, Box::new(child.stderr.take().ok_or("Backend diagnostics missing.")?) as Box<dyn Read + Send>, 64 * 1024),
        ] {
            let send = send.clone();
            std::thread::spawn(move || {
                let mut bytes = Vec::new();
                let result = pipe.take(limit + 1).read_to_end(&mut bytes)
                    .map_err(|_| "Backend output interrupted.")
                    .and_then(|_| if bytes.len() as u64 > limit { Err("Backend response exceeded its size limit.") } else { Ok(bytes) });
                let _ = send.send((is_stdout, result));
            });
        }
        drop(send);
        let deadline = Instant::now() + Duration::from_secs(85);
        let mut stdout = None;
        let mut complete = 0;
        while complete < 2 || child.try_wait().map_err(|_| "Backend process unavailable.")?.is_none() {
            if Instant::now() >= deadline {
                stop_read(&mut child);
                return Err(format!("Backend {collection} request timed out. Refresh to retry; no rental was started."));
            }
            match receive.recv_timeout(Duration::from_millis(50)) {
                Ok((is_stdout, Ok(bytes))) => { complete += 1; if is_stdout { stdout = Some(bytes); } },
                Ok((_, Err(message))) => { stop_read(&mut child); return Err(message.to_string()); },
                Err(mpsc::RecvTimeoutError::Disconnected) => std::thread::sleep(Duration::from_millis(20)),
                Err(mpsc::RecvTimeoutError::Timeout) => (),
            }
        }
        let status = child.wait().map_err(|_| "Backend process unavailable.")?;
        if !status.success() {
            if status.code() == Some(124) || status.code() == Some(137) {
                return Err(format!("Backend {collection} request timed out. Refresh to retry."));
            }
            return Err(format!("Backend {collection} request failed (exit {}). Check Vastgame configuration and retry.", status.code().unwrap_or(-1)));
        }
        let data: serde_json::Value = serde_json::from_slice(&stdout.unwrap_or_default())
            .map_err(|_| format!("Backend {collection} response is invalid JSON. Update the backend and retry."))?;
        if data.get("error").is_some_and(|error| error.is_object()) { return Ok(data); }
        if !data.get(collection).is_some_and(|value| match collection {
            "image" => value.is_null() || value.is_string(),
            "details" | "quote" | "session" => value.is_null() || value.is_object(),
            _ => value.is_array(),
        }) { return Err(format!("Backend {collection} response has an invalid format.")); }
        Ok(data)
    }).await.map_err(|_| "Backend request worker could not finish.".to_string())?
}

pub fn command(args: &[String], read_only: bool) -> Result<Command, String> {
    #[cfg(target_os = "windows")]
    let mut command = {
        use std::os::windows::process::CommandExt;
        let mut cmd = Command::new("wsl.exe");
        cmd.args(["--distribution", "Vastgame", "--user", "vastgame", "--exec"]);
        if read_only { cmd.args(["timeout", "--kill-after=5s", "75s"]); }
        cmd.arg("/home/vastgame/.local/bin/vastgame");
        cmd.creation_flags(0x08000000);
        cmd
    };
    #[cfg(not(target_os = "windows"))]
    let mut command = {
        let home = std::path::PathBuf::from(std::env::var_os("HOME").ok_or("Cannot locate your Vastgame installation.")?);
        let mut cmd = if read_only { let mut cmd = Command::new("timeout"); cmd.args(["--kill-after=5s", "75s"]); cmd.arg(home.join(".local/bin/vastgame")); cmd }
            else { Command::new(home.join(".local/bin/vastgame")) };
        let mut paths = vec![home.join(".local/bin")];
        if let Some(path) = std::env::var_os("PATH") { paths.extend(std::env::split_paths(&path)); }
        cmd.env("PATH", std::env::join_paths(paths).map_err(|_| "Cannot locate backend tools.")?);
        #[cfg(unix)]
        if read_only { use std::os::unix::process::CommandExt; cmd.process_group(0); }
        cmd
    };
    command.args(args);
    Ok(command)
}

#[cfg(test)]
mod tests {
    #[test]
    fn game_ids_match_backend_rules() {
        for id in ["game", "re9", "game-1_v2.0"] { assert!(super::valid_game_id(id)); }
        for id in ["", ".game", "-game", "../game", "Game", "game/name"] { assert!(!super::valid_game_id(id)); }
        assert!(!super::valid_game_id(&"a".repeat(65)));
    }
}
