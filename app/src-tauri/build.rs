fn main() {
    // 应用命令只开放 run_selfcheck（capabilities/default.json 用 allow-run-selfcheck 授权）
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&["run_selfcheck"])))
        .expect("tauri build 失败")
}
