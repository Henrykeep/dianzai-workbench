// 电赛工作台外壳：只负责开窗口 + 拉起/收掉侧车。所有协议逻辑都在 Python 侧车里（可单独测试）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct Sidecar(Mutex<Option<CommandChild>>);

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // 打包版：binaries/dzbench-<triple>（PyInstaller）。开发版找不到时退回 python -m dzbench。
            let child = match app.shell().sidecar("dzbench") {
                Ok(cmd) => cmd.args(["--port", "8765"]).spawn().ok().map(|(_, c)| c),
                Err(_) => None,
            }
            .or_else(|| {
                let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../sidecar");
                ["python3", "python"].iter().find_map(|py| {
                    app.shell().command(py).args(["-m", "dzbench", "--port", "8765"]).current_dir(dir)
                        .spawn().ok().map(|(_, c)| c)
                })
            });
            if child.is_none() {
                eprintln!("dzbench: 侧车没能启动；界面会提示并持续重连");
            }
            app.manage(Sidecar(Mutex::new(child)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tauri 启动失败");
    app.run(|h, ev| {
        if let RunEvent::Exit = ev {
            if let Some(c) = h.state::<Sidecar>().0.lock().unwrap().take() {
                let _ = c.kill();
            }
        }
    });
}
