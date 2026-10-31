// 芯台外壳：开窗口 + 拉起/看护/收掉侧车。所有协议逻辑都在 Python 侧车里（可单独测试）。
// 看护：侧车意外退出就 1 s 后重启（60 s 内最多 5 次）；退出码 3 = 端口被占（已经开着一个），不重启。
// 只允许一个窗口：再双击图标会把已有窗口拉到前面，而不是再起一个侧车抢串口。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

// 侧车连不上时的数据表自检：只跑这一个脚本、只用这几个解释器（与 app/ui/src/fieldmap.ts SELFCHECK_F 一致）
const SELFCHECK_SCRIPT: &str = "app/sidecar/selfcheck_data.py";
const SELFCHECK_PY_WIN: &str = "python/python.exe";
const SELFCHECK_PY_VENV: &str = ".venv/bin/python";
const SELFCHECK_PY_SYS: [&str; 2] = ["python3.12", "python3"];
const EXIT_PORT_IN_USE: i32 = 3; // 与 dzbench/__main__.py 一致
const MAX_RESTARTS: usize = 5;
const RESTART_WINDOW: Duration = Duration::from_secs(60);

struct Sidecar {
    child: Mutex<Option<CommandChild>>,
    exiting: AtomicBool,
}

type Spawned = (tauri::async_runtime::Receiver<CommandEvent>, CommandChild);

fn spawn_sidecar(app: &AppHandle) -> Option<Spawned> {
    // 打包版：binaries/dzbench-<triple>（PyInstaller）。开发版找不到时退回 python -m dzbench。
    let packaged = app
        .shell()
        .sidecar("dzbench")
        .ok()
        .and_then(|c| c.args(["--port", "8765"]).spawn().ok());
    packaged.or_else(|| {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../sidecar");
        ["python3", "python"].iter().find_map(|py| {
            app.shell()
                .command(py)
                .args(["-m", "dzbench", "--port", "8765"])
                .current_dir(dir)
                .spawn()
                .ok()
        })
    })
}

fn supervise(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut starts: Vec<Instant> = Vec::new();
        loop {
            let Some((mut rx, child)) = spawn_sidecar(&app) else {
                eprintln!("dzbench: 侧车没能启动；界面会提示并持续重连");
                return;
            };
            starts.push(Instant::now());
            *app.state::<Sidecar>().child.lock().unwrap() = Some(child);
            let mut code = None;
            while let Some(ev) = rx.recv().await {
                if let CommandEvent::Terminated(p) = ev {
                    code = p.code;
                    break;
                }
            }
            let st = app.state::<Sidecar>();
            st.child.lock().unwrap().take();
            if st.exiting.load(Ordering::SeqCst) {
                return;
            }
            if code == Some(EXIT_PORT_IN_USE) {
                eprintln!("dzbench: 端口 8765 已被占用（已经开着一个工作台？），不再重启侧车");
                return;
            }
            starts.retain(|t| t.elapsed() < RESTART_WINDOW);
            if starts.len() >= MAX_RESTARTS {
                eprintln!("dzbench: 侧车 1 分钟内退出了 {MAX_RESTARTS} 次，停止重启；界面会一直显示“侧车没有响应”");
                return;
            }
            eprintln!("dzbench: 侧车退出（code {code:?}），1 秒后重启");
            let _ = tauri::async_runtime::spawn_blocking(|| std::thread::sleep(Duration::from_secs(1))).await;
        }
    });
}

/// 正常关窗口时侧车是被直接杀掉的，来不及删“上次连接”记录；这里替它删，免得下次启动误报“侧车崩溃”。
/// 路径规则与 dzbench/snapshots.py::base_dir 一致。
fn clear_last_session() {
    let base = std::env::var_os("DZBENCH_HOME").map(std::path::PathBuf::from).or_else(|| {
        std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(|h| std::path::PathBuf::from(h).join(".dzbench"))
    });
    if let Some(b) = base {
        let _ = std::fs::remove_file(b.join("last_session.json"));
    }
}

/// 安装目录 = 可执行文件所在目录；开发版退回仓库根（CARGO_MANIFEST_DIR/../..）
fn install_dirs() -> Vec<std::path::PathBuf> {
    let mut v = Vec::new();
    if let Some(d) = std::env::current_exe().ok().and_then(|e| e.parent().map(|p| p.to_path_buf())) {
        v.push(d);
    }
    v.push(std::path::PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../..")));
    v
}

/// 只运行固定的自检脚本（不接受前端任何参数），返回它 stdout 的 JSON 文本 {ok, items}
#[tauri::command]
fn run_selfcheck() -> Result<String, String> {
    for base in install_dirs() {
        let script = base.join(SELFCHECK_SCRIPT);
        if !script.is_file() {
            continue;
        }
        let mut pys: Vec<std::ffi::OsString> = Vec::new();
        if cfg!(windows) {
            pys.push(base.join(SELFCHECK_PY_WIN).into_os_string());
        } else {
            let venv = base.join(SELFCHECK_PY_VENV);
            if venv.is_file() {
                pys.push(venv.into_os_string());
            }
            for p in SELFCHECK_PY_SYS {
                pys.push(p.into());
            }
        }
        for py in pys {
            if let Ok(out) = std::process::Command::new(&py).arg(&script).current_dir(&base).output() {
                let s = String::from_utf8_lossy(&out.stdout).to_string();
                if !s.trim().is_empty() {
                    return Ok(s);
                }
            }
        }
        return Err("no_python".into());
    }
    Err("no_script".into())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![run_selfcheck])
        .setup(|app| {
            app.manage(Sidecar { child: Mutex::new(None), exiting: AtomicBool::new(false) });
            supervise(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tauri 启动失败");
    app.run(|h, ev| {
        if let RunEvent::Exit = ev {
            let st = h.state::<Sidecar>();
            st.exiting.store(true, Ordering::SeqCst);
            if let Some(c) = st.child.lock().unwrap().take() {
                let _ = c.kill();
            }
            clear_last_session();
        }
    });
}
