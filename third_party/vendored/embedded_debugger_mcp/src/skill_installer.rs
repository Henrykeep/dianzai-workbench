use embedded_debugger_mcp::config::SkillInstallTarget;
use serde::Serialize;
use std::path::{Path, PathBuf};

pub(crate) const DEFAULT_SKILL_PROMPT: &str =
    include_str!("../skills/embedded-debugger/references/default-prompt.md");

const EMBEDDED_DEBUGGER_SKILL_MD: &str = include_str!("../skills/embedded-debugger/SKILL.md");
const EMBEDDED_DEBUGGER_OPENAI_YAML: &str =
    include_str!("../skills/embedded-debugger/agents/openai.yaml");
const EMBEDDED_DEBUGGER_CLAUDE_PLUGIN_JSON: &str = include_str!("../.claude-plugin/plugin.json");
const SKILL_NAME: &str = "embedded-debugger";
const CLAUDE_PLUGIN_DIR_NAME: &str = "embedded-debugger-mcp";

#[derive(Debug, Serialize)]
pub(crate) struct SkillInstallReport {
    target: String,
    home: PathBuf,
    dry_run: bool,
    force: bool,
    entries: Vec<SkillInstallEntry>,
    next_steps: Vec<String>,
}

impl SkillInstallReport {
    pub(crate) fn print_text(&self) {
        println!("embedded-debugger skill install");
        println!("target: {}", self.target);
        println!("home: {}", self.home.display());
        println!("dry_run: {}", self.dry_run);
        for entry in &self.entries {
            println!(
                "{}: {} ({})",
                entry.kind,
                entry.path.display(),
                entry.status
            );
        }
        if !self.next_steps.is_empty() {
            println!("next:");
            for step in &self.next_steps {
                println!("- {}", step);
            }
        }
    }
}

#[derive(Debug, Serialize)]
struct SkillInstallEntry {
    kind: &'static str,
    path: PathBuf,
    status: &'static str,
}

#[derive(Debug, Clone, Copy)]
enum SkillInstallKind {
    CodexSkill,
    ClaudeSkill,
    ClaudePlugin,
}

impl SkillInstallKind {
    fn label(self) -> &'static str {
        match self {
            Self::CodexSkill => "codex-skill",
            Self::ClaudeSkill => "claude-skill",
            Self::ClaudePlugin => "claude-plugin",
        }
    }

    fn path(self, home: &Path) -> PathBuf {
        match self {
            Self::CodexSkill => home.join(".codex").join("skills").join(SKILL_NAME),
            Self::ClaudeSkill => home.join(".claude").join("skills").join(SKILL_NAME),
            Self::ClaudePlugin => home
                .join(".claude")
                .join("plugins")
                .join("local")
                .join(CLAUDE_PLUGIN_DIR_NAME),
        }
    }

    fn write(self, path: &Path) -> std::io::Result<()> {
        match self {
            Self::CodexSkill | Self::ClaudeSkill => write_skill_directory(path),
            Self::ClaudePlugin => write_claude_plugin_directory(path),
        }
    }
}

pub(crate) fn install_skill_bundle(
    target: SkillInstallTarget,
    home: Option<PathBuf>,
    dry_run: bool,
    force: bool,
) -> Result<SkillInstallReport, Box<dyn std::error::Error>> {
    let home = resolve_install_home(home)?;
    let kinds = skill_install_kinds(target);

    if !dry_run && !force {
        for kind in &kinds {
            let path = kind.path(&home);
            if path.exists() {
                return Err(format!(
                    "{} already exists at {}; rerun with --force to replace it or --dry-run to preview",
                    kind.label(),
                    path.display()
                )
                .into());
            }
        }
    }

    let mut entries = Vec::with_capacity(kinds.len());
    for kind in kinds {
        let path = kind.path(&home);
        let existed = path.exists();
        let status = if dry_run {
            if existed {
                "would_replace"
            } else {
                "would_install"
            }
        } else {
            if existed {
                remove_existing_path(&path)?;
            }
            kind.write(&path)?;
            "installed"
        };
        entries.push(SkillInstallEntry {
            kind: kind.label(),
            path,
            status,
        });
    }

    Ok(SkillInstallReport {
        target: skill_install_target_label(target).to_string(),
        home: home.clone(),
        dry_run,
        force,
        next_steps: skill_install_next_steps(target, &home),
        entries,
    })
}

fn resolve_install_home(home: Option<PathBuf>) -> Result<PathBuf, Box<dyn std::error::Error>> {
    if let Some(home) = home {
        return Ok(home);
    }
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .ok_or_else(|| "HOME is not set; pass --home <path>".into())
}

fn skill_install_kinds(target: SkillInstallTarget) -> Vec<SkillInstallKind> {
    match target {
        SkillInstallTarget::Codex => vec![SkillInstallKind::CodexSkill],
        SkillInstallTarget::Claude => {
            vec![
                SkillInstallKind::ClaudeSkill,
                SkillInstallKind::ClaudePlugin,
            ]
        }
        SkillInstallTarget::Both => vec![
            SkillInstallKind::CodexSkill,
            SkillInstallKind::ClaudeSkill,
            SkillInstallKind::ClaudePlugin,
        ],
    }
}

fn skill_install_target_label(target: SkillInstallTarget) -> &'static str {
    match target {
        SkillInstallTarget::Codex => "codex",
        SkillInstallTarget::Claude => "claude",
        SkillInstallTarget::Both => "both",
    }
}

fn skill_install_next_steps(target: SkillInstallTarget, home: &Path) -> Vec<String> {
    let mut steps = Vec::new();
    if matches!(target, SkillInstallTarget::Codex | SkillInstallTarget::Both) {
        steps.push("Use `$embedded-debugger` in Codex.".to_string());
    }
    if matches!(
        target,
        SkillInstallTarget::Claude | SkillInstallTarget::Both
    ) {
        let plugin_path = SkillInstallKind::ClaudePlugin.path(home);
        steps.push(format!(
            "Use `claude --plugin-dir {} --print '/embedded-debugger inspect my embedded target setup'`.",
            plugin_path.display()
        ));
    }
    steps
}

fn write_skill_directory(path: &Path) -> std::io::Result<()> {
    write_text_file(&path.join("SKILL.md"), EMBEDDED_DEBUGGER_SKILL_MD)?;
    write_text_file(
        &path.join("agents").join("openai.yaml"),
        EMBEDDED_DEBUGGER_OPENAI_YAML,
    )?;
    write_text_file(
        &path.join("references").join("default-prompt.md"),
        DEFAULT_SKILL_PROMPT,
    )?;
    Ok(())
}

fn write_claude_plugin_directory(path: &Path) -> std::io::Result<()> {
    write_text_file(
        &path.join(".claude-plugin").join("plugin.json"),
        EMBEDDED_DEBUGGER_CLAUDE_PLUGIN_JSON,
    )?;
    write_skill_directory(&path.join("skills").join(SKILL_NAME))
}

fn write_text_file(path: &Path, content: &str) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, content)
}

fn remove_existing_path(path: &Path) -> std::io::Result<()> {
    if path.is_dir() {
        std::fs::remove_dir_all(path)
    } else {
        std::fs::remove_file(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_skill_install_writes_codex_and_claude_bundle() {
        let home = tempfile::tempdir().expect("temp home");
        let report = install_skill_bundle(
            SkillInstallTarget::Both,
            Some(home.path().to_path_buf()),
            false,
            false,
        )
        .expect("install skill bundle");

        assert_eq!(report.entries.len(), 3);
        assert!(home
            .path()
            .join(".codex/skills/embedded-debugger/SKILL.md")
            .is_file());
        assert!(home
            .path()
            .join(".claude/skills/embedded-debugger/SKILL.md")
            .is_file());
        assert!(home
            .path()
            .join(".claude/plugins/local/embedded-debugger-mcp/.claude-plugin/plugin.json")
            .is_file());
        assert!(home
            .path()
            .join(".claude/plugins/local/embedded-debugger-mcp/skills/embedded-debugger/references/default-prompt.md")
            .is_file());

        let duplicate = install_skill_bundle(
            SkillInstallTarget::Codex,
            Some(home.path().to_path_buf()),
            false,
            false,
        );
        assert!(duplicate.is_err());

        let dry_run = install_skill_bundle(
            SkillInstallTarget::Codex,
            Some(home.path().to_path_buf()),
            true,
            false,
        )
        .expect("dry-run existing install");
        assert_eq!(dry_run.entries[0].status, "would_replace");
    }
}
