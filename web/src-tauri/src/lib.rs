use std::fs;
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{Manager, State};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct DesktopState {
  api_base: String,
  _sidecar: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn desktop_api_base(state: State<'_, DesktopState>) -> String {
  state.api_base.clone()
}

fn allocate_local_port() -> Result<u16, String> {
  let listener = TcpListener::bind("127.0.0.1:0").map_err(|err| err.to_string())?;
  let address = listener.local_addr().map_err(|err| err.to_string())?;
  Ok(address.port())
}

fn app_data_paths(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf, PathBuf), String> {
  let app_data_dir = app.path().app_data_dir().map_err(|err| err.to_string())?;
  fs::create_dir_all(&app_data_dir).map_err(|err| err.to_string())?;
  Ok((
    app_data_dir.join("game_state.json"),
    app_data_dir.join("runtime_settings.json"),
    app_data_dir.join("llm_credentials.json"),
  ))
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<DesktopState, String> {
  let port = allocate_local_port()?;
  let (state_path, runtime_settings_path, credentials_path) = app_data_paths(app)?;
  let (_events, child) = app
    .shell()
    .sidecar("dungeon-master-backend")
    .map_err(|err| err.to_string())?
    .args([
      "--host",
      "127.0.0.1",
      "--port",
      &port.to_string(),
    ])
    .env("DUNGEON_MASTER_STATE_PATH", state_path.to_string_lossy().into_owned())
    .env(
      "DUNGEON_MASTER_RUNTIME_SETTINGS_PATH",
      runtime_settings_path.to_string_lossy().into_owned(),
    )
    .env(
      "DUNGEON_MASTER_CREDENTIALS_PATH",
      credentials_path.to_string_lossy().into_owned(),
    )
    .spawn()
    .map_err(|err| err.to_string())?;
  Ok(DesktopState {
    api_base: format!("http://127.0.0.1:{port}/api"),
    _sidecar: Mutex::new(Some(child)),
  })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let mut builder = tauri::Builder::default().plugin(tauri_plugin_shell::init());
  if cfg!(debug_assertions) {
    builder = builder.plugin(
      tauri_plugin_log::Builder::default()
        .level(log::LevelFilter::Info)
        .build(),
    );
  }
  builder
    .setup(|app| {
      let state = spawn_backend(app.handle())?;
      app.manage(state);
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![desktop_api_base])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
