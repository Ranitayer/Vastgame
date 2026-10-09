#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod backend;
mod hosts;
mod library;
mod launch;

fn main() {
    tauri::Builder::default()
        .manage(launch::LaunchState::default())
        .invoke_handler(tauri::generate_handler![hosts::browse_hosts, library::browse_library, library::game_artwork, library::game_details, launch::follow_launch, launch::current_launch, launch::quote_game, launch::launch_game, launch::connect_game, launch::shutdown_game])
        .run(tauri::generate_context!())
        .expect("Vastgame desktop could not start");
}
