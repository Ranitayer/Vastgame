#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod hosts;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![hosts::browse_hosts])
        .run(tauri::generate_context!())
        .expect("Vastgame desktop could not start");
}
