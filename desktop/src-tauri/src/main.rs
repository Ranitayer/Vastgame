#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod backend;
mod account;
mod hosts;
mod library;
mod launch;
mod sessions;
mod settings;

fn main() {
    tauri::Builder::default()
        .manage(launch::LaunchState::default())
        .invoke_handler(tauri::generate_handler![settings::read_settings, settings::save_settings, settings::reset_settings, settings::sensitive_settings, account::account_balance, hosts::browse_hosts, library::browse_library, library::game_artwork, library::game_details, launch::follow_launch, launch::current_launch, launch::quote_game, launch::launch_game, launch::connect_game, launch::shutdown_game, sessions::browse_sessions, sessions::prepare_session, sessions::session_logs, sessions::session_events])
        .run(tauri::generate_context!())
        .expect("Vastgame desktop could not start");
}
