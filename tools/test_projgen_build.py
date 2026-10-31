"""#52：工作台给题目工程导出 <工程>/build/gen/（gen_project 生成物，给 Keil/IDE 用）后，
make BOARD=host-sim 不能把它和 $(OUT)/projgen 里的同名生成源各编一份（重复定义 cp_vision_cpu_params 等）。
python3 tools/test_projgen_build.py"""
import os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = "2026H_ball"


def main():
    with tempfile.TemporaryDirectory() as d:
        home = pathlib.Path(d) / "home"
        proj = home / "projects" / APP
        shutil.copytree(ROOT / "examples" / APP, proj, ignore=shutil.ignore_patterns("build", "tests"))
        # 与侧车 projflow 一样：把生成物导出到 <工程>/build/gen/
        subprocess.run([sys.executable, str(ROOT / "tools/gen_project.py"), str(proj / "project.yaml"),
                        "-o", str(proj / "build/gen"), "--role", "main"], cwd=ROOT, check=True, capture_output=True)
        gen = sorted(p.name for p in (proj / "build/gen").glob("*.c"))
        assert "project_gen.c" in gen and "cp_vision_cpu.c" in gen, gen
        env = {k: v for k, v in os.environ.items() if not k.startswith("DZ_LLM_")}
        env.update(DZBENCH_HOME=str(home))
        out = pathlib.Path(d) / "out"
        cp = subprocess.run(["make", "-s", "BOARD=host-sim", f"APP={APP}", f"OUT={out}"], cwd=ROOT, env=env,
                            capture_output=True, text=True)
        log = cp.stdout + cp.stderr
        assert cp.returncode == 0 and "multiple definition" not in log, log[-3000:]
        assert (out / f"{APP}.elf").exists(), log[-2000:]
        assert not list((out / "obj").rglob("build/gen/*.o")), "工程 build/gen 下的生成源被编进去了"
    print("题目工程带 build/gen 导出物时 host-sim 只链一份生成源：通过")


if __name__ == "__main__":
    main()
