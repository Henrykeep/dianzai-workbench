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

// 侧车连不上时的数据表自检：只允许这两个入口（与 app/ui/src/fieldmap.ts SELFCHECK_F 一致）
// Windows：<安装目录>/python/python.exe <安装目录>/repo/app/sidecar/selfcheck_data.py（代码在 repo\\ 下，同 fw-pyembed 布局）；Linux/macOS：直接运行仓库根的 xintai-selfcheck.sh
const SELFCHECK_PY_WIN: &str = "python/python.exe";
const SELFCHECK_SCRIPT_WIN: &str = "repo/app/sidecar/selfcheck_data.py";
const SELFCHECK_SH: &str = "xintai-selfcheck.sh";
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

/// 只运行固定的自检入口（不接受前端任何参数，不在 PATH 里找解释器），返回 {exit_code, report:{ok, items}}
#[tauri::command]
fn run_selfcheck() -> Result<String, String> {
    for base in install_dirs() {
        let mut cmd = if cfg!(windows) {
            let (py, script) = (base.join(SELFCHECK_PY_WIN), base.join(SELFCHECK_SCRIPT_WIN));
            if !py.is_file() || !script.is_file() {
                continue;
            }
            let mut c = std::process::Command::new(py);
            c.arg(script);
            c
        } else {
            let sh = base.join(SELFCHECK_SH);
            if !sh.is_file() {
                continue;
            }
            std::process::Command::new(sh)
        };
        let out = cmd.current_dir(&base).output().map_err(|_| "spawn_failed".to_string())?;
        let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if s.is_empty() {
            return Err("no_output".into());
        }
        // 退出码一起带回：0 通过 / 1 失败 / 3 未完成（有未检查项）；report 原样是脚本的 JSON
        let code = out.status.code().unwrap_or(-1);
        return Ok(format!("{{\"exit_code\":{},\"report\":{}}}", code, s));
    }
    Err("not_installed".into())
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
