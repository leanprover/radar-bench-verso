#!/usr/bin/env python
# This script is invoked by Radar infrastructure
# to measure the build time of projects downstream of Verso.
# We prefer the version of this script in verso/bench.py,
# but this copy can be used to benchmark old versions that don't include it.

import argparse
import json
import os.path
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

output_path: Path
root: str
cmdargs: list[str]


def append_result(
    metric: str,
    submetric: str,
    value: str | float | int,
    unit=None,
    more_is_better: Any = False,
) -> None:
    global output_path
    global root
    val = str(value)

    # Infer units a little bit
    if unit is None:
        match_val = re.match(r"([0-9.]+)ms", val)
        if match_val:
            val = str(float(match_val[1]) / 1000)
            unit = "s"

    if unit is None:
        # Supported: s for sec, B for bytes
        match_val = re.match(r"([0-9.]+)([%a-zA-Z]+)", val)
        if match_val:
            val = match_val[1]
            unit = match_val[2]

    print(f"{metric} // {submetric} -> {val}{f'({unit})' if unit else ''}")
    with open(output_path, "a") as f:
        f.write(
            json.dumps(
                {
                    "metric": f"{root}/{metric}//{submetric}",
                    "value": val,
                    "unit": unit,
                    "direction": 1 if more_is_better else -1,
                }
            )
            + "\n"
        )


def walk_ir_dir(project_directory: Path):
    total_c = 0
    ir_dir = Path.cwd() / project_directory / ".lake" / "build" / "ir"
    for dir_, _, files in os.walk(ir_dir):
        module_base = list(Path(dir_).relative_to(ir_dir).parts)
        for file in files:
            if file.endswith(".c"):
                module = ".".join(module_base + [file[:-2]])
                size = os.path.getsize(Path(dir_) / file)
                total_c += size
                append_result(f"build/{module}", "generated C", size, "B")
    append_result("build/.total", "generated C", total_c, "B")


def walk_lib_dir(project_directory: Path):
    total_olean = 0
    lib_dir = Path.cwd() / project_directory / ".lake" / "build" / "lib" / "lean"
    for dir_, _, files in os.walk(lib_dir):
        module_base = list(Path(dir_).relative_to(lib_dir).parts)
        for file in files:
            if file.endswith(".olean"):
                module = ".".join(module_base + [file[:-6]])
                size = os.path.getsize(Path(dir_) / file)
                total_olean += size
                append_result(f"build/{module}", "generated olean", size, "B")
    append_result("build/.total", "generated olean", total_olean, "B")


def checkout_project(
    verso_directory: Path,
    gitUrl: str,
    project_directory: Path,
    useO0: bool,
    branch: str,
):
    """
    Checkout a suitably structured Verso project in an indicated directory.
    The project is rewritten to use the toolchain (& corresponding packages)
    for the Verso version being benchmarked.
    """

    try:
        with open(verso_directory / "lean-toolchain") as f:
            versos_lean_toolchain = f.read().strip()
            if not versos_lean_toolchain.startswith("leanprover/lean4:"):
                raise Exception(
                    f"lean toolchain for verso isn't a lean4 version: {versos_lean_toolchain}"
                )
            verso_lean_version = versos_lean_toolchain[17:]

        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                gitUrl,
                f"--branch={branch}",
                project_directory,
            ],
            capture_output=True,
            check=True,
        )

        # Before we replace the project's lean toolchain, read it so
        # we can use it to rewrite the lakefile
        with open(Path.cwd() / project_directory / "lean-toolchain") as f:
            project_lean_toolchain = f.read().strip()
            if not project_lean_toolchain.startswith("leanprover/lean4:"):
                raise Exception(
                    f"lean toolchain for project isn't a lean4 version: {project_lean_toolchain}"
                )
            project_lean_version = project_lean_toolchain[17:]
        with open(Path.cwd() / project_directory / "lean-toolchain", "w") as f:
            f.write(versos_lean_toolchain)

        lakefile: Path = Path.cwd() / project_directory / "lakefile.lean"
        with open(lakefile) as f:
            lines = f.readlines()
            for index, line in enumerate(lines):
                if re.match(r"^require verso from ", line):
                    lines[index] = f'require verso from "{verso_directory}"\n'
                elif re.match(r"^package", line) and useO0:
                    lines[index] = line + '  moreLeancArgs := #["-O0"]\n'
                else:
                    lines[index] = line.replace(
                        f'"{project_lean_version}"', f'"{verso_lean_version}"'
                    )
        with open(lakefile, "w") as f:
            f.write("".join(lines))
        append_result("checkout", "success", 1, more_is_better=True)
        return True
    except Exception as e:
        print(e)
        append_result("checkout", "success", 0, more_is_better=True)
        return False


def project_build_default(project_directory: Path) -> bool:
    try:
        subprocess.run(
            ["lake", "update", "--no-ansi", "--keep-toolchain"],
            cwd=project_directory,
            check=True,
        )
        start: float = time.time()
        result = subprocess.run(
            ["lake", "build", "--no-ansi", "--keep-toolchain"],
            cwd=project_directory,
            capture_output=True,
        )
        end: float = time.time()
        print(end - start)
        append_result("build/default/.total", "wall clock time", end - start, "s")
        process_output("build/default", result.stdout.decode("utf-8"))
        print(result.stderr.decode("utf-8"), file=sys.stderr)
        result.check_returncode()
        append_result("build/default", "success", 1, more_is_better=True)
        return True
    except subprocess.SubprocessError as e:
        print(f"compilation failed {e}")
        append_result("build/default", "success", 0, more_is_better=True)
        return False
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("build/default", "success", 0, more_is_better=True)
        return False


def project_build_exe(project_directory: Path, name: str) -> bool:
    try:
        start: float = time.time()
        result = subprocess.run(
            ["lake", "build", name, "--no-ansi", "--keep-toolchain"],
            cwd=project_directory,
            capture_output=True,
        )
        end: float = time.time()
        print(end - start)
        append_result("build/exe/.total", "wall clock time", end - start, "s")
        process_output("build/exe", result.stdout.decode("utf-8"))
        print(result.stderr.decode("utf-8"), file=sys.stderr)
        result.check_returncode()
        append_result("build/exe", "success", 1, more_is_better=True)
        return True
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("build/exe", "success", 0, more_is_better=True)
        return False

def project_run_exe(project_directory: Path, exe_name: str) -> bool:
    try:
        exe_path = Path.cwd() / project_directory / ".lake" / "build" / "bin" / exe_name
        exe_size = os.path.getsize(exe_path)
        append_result("build/exe", "generated exe", exe_size, "B")
        start: float = time.time()
        subprocess.run(
            [str(exe_path)] + cmdargs,
            cwd=project_directory,
            check=True,
        )
        end: float = time.time()
        append_result("execute", "generation time", end - start, "s")
        append_result("execute", "success", 1, more_is_better=True)
        return True
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("execute", "success", 0, more_is_better=True)
        return False

def parse_time(time: str):
    time = time.strip()
    match_val = re.match(r"([0-9.]+)ms$", time)
    if match_val:
        return float(match_val[1]) / 1000
    match_val = re.match(r"([0-9.]+)s$", time)
    if match_val:
        return float(match_val[1])
    print(f"cannot parse time {time}")
    raise Exception("Cannot parse time")


total_key_time: dict[str, float] = {}
subtotals_key_time: dict[str, dict[str, float]] = {}


def process_output(prefix: str, output: str):
    global total_key_time
    global subtotals_key_time

    totals: dict[str, float] = {}

    for line in output.split("\n"):
        match_val_eval_metric = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )
        match_val_other_metric = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+):([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )

        if match_val_eval_metric:
            metric: str = "eval"
            time_data: float = parse_time(match_val_eval_metric[4])
            module_name = match_val_eval_metric[3]
            top_level_module: str = match_val_eval_metric[3].split(".")[0]
        elif match_val_other_metric:
            metric = match_val_other_metric[4]
            time_data = parse_time(match_val_other_metric[5])
            module_name = match_val_other_metric[3]
            top_level_module = match_val_other_metric[3].split(".")[0]
        elif re.match(r"[^]]*\]\s*Built", line):
            print(f"MISSED?: {line}", file=sys.stderr)
            continue
        else:
            print(line)
            continue

        append_result(f"{prefix}/{module_name}", f"{metric} time", time_data, "s")
        print(line)

        # Update total
        prev_total = totals.get(metric, 0.0)
        totals[metric] = prev_total + time_data

        # Update per-package subtotal
        if top_level_module not in subtotals_key_time:
            subtotals_key_time[top_level_module] = {}
        prev_subtotal = subtotals_key_time[top_level_module].get(metric, 0.0)
        subtotals_key_time[top_level_module][metric] = prev_subtotal + time_data

    for key, total in totals.items():
        if key not in total_key_time:
            total_key_time[key] = 0
        total_key_time[key] += total
        append_result(f"{prefix}/.total", f"{key} time", total, "s")


def main() -> None:
    global output_path
    global root
    global total_key_time
    global subtotals_key_time
    global cmdargs

    parser = argparse.ArgumentParser(
        description="Collect timing and output size data from building a Verso project and generating its artifacts. "
          "Output in Radar format."
    )

    parser.add_argument(
        "output_path",
        type=Path,
        help="file the measurements should be appended to (created if missing)",
    )
    parser.add_argument("-r", "--metrics-root", type=str, help="first component of reported Radar metric names", required=True)
    parser.add_argument("-e", "--exe-name", type=str, help="name of the Verso doc generator lean_exe", required=True)
    parser.add_argument("--exe-arg", action="append", help="additional argument to pass to the doc generator (use --exe-arg=--foo syntax)", default=[])
    parser.add_argument("--opt", type=str, help="optimization level for native compilation (must be o0 if provided)")
    parser.add_argument("--project-url", type=str, help="Git URL of the project to benchmark")
    parser.add_argument("--project-branch", type=str, help="branch of the project to clone")
    parser.add_argument("--project-dir", type=Path, help="directory to clone the project into (or to read the project from with --skip-checkout)", default="project")
    parser.add_argument("--skip-checkout", action="store_true", help="do not clone the project, assuming it is already in --project-dir")
    parser.add_argument("--verso-dir", type=Path, help="Verso checkout directory")
    
    args = parser.parse_args()

    output_path = args.output_path
    directory = args.project_dir
    root = args.metrics_root
    binary = args.exe_name
    cmdargs = args.exe_arg
    if args.verso_dir is not None:
        verso_directory = args.verso_dir
    else:
        verso_directory = Path(__file__).resolve().parent

    if args.opt == "o0":
        use_o0_optimization = True
    elif args.opt is not None:
        print(f"unexpected opt level {args.opt}", file=sys.stderr)
        sys.exit(1)
    else:
        use_o0_optimization = False

    if not args.skip_checkout:
        if args.project_url is None:
            print(f"--project-url must be provided when not using --skip-checkout", file=sys.stderr)
            sys.exit(1)
        if args.project_branch is None:
            print(f"--project-branch must be provided when not using --skip-checkout", file=sys.stderr)
            sys.exit(1)

        did_checkout = checkout_project(
            verso_directory=verso_directory,
            gitUrl=args.project_url,
            branch=args.project_branch,
            useO0=use_o0_optimization,
            project_directory=directory,
        )
    else:
        did_checkout = True

    if not did_checkout:
        print("checkout did not succeed")
        sys.exit(1)

    # Clean in case the script had already run on a different downstream project
    # and constructed `.lake` in the Verso directory.
    subprocess.run(
        ["lake", "clean", "--no-ansi", "--keep-toolchain"],
        cwd=verso_directory,
        check=True,
    )

    did_build = project_build_default(directory)
    if not did_build:
        print("default build step did not succeed")
        sys.exit(1)

    did_compile = project_build_exe(directory, binary)
    if not did_compile:
        print("exe build step did not succeed")
        sys.exit(1)

    walk_ir_dir(directory)
    walk_lib_dir(directory)

    for key, total in total_key_time.items():
        append_result("build/.total", f"{key} time", total, "s")
    for top_level_package, kv in subtotals_key_time.items():
        for key, total in kv.items():
            append_result(
                f"build/{top_level_package}/.total", f"{key} time", total, "s"
            )

    did_run = project_run_exe(directory, binary)
    if not did_run:
        print("exe run step did not succeed")
        sys.exit(1)

if __name__ == "__main__":
    main()
