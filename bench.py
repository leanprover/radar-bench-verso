#!/usr/bin/env python

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


def walk_ir_dir(project_directory: str):
    total_c = 0
    ir_dir = Path.cwd() / project_directory / ".lake" / "build" / "ir"
    for root, dirs, files in os.walk(ir_dir):
        module_base = root.split(f"{project_directory}/.lake/build/ir")[1].split("/")[
            1:
        ]
        for file in files:
            if file.endswith(".c"):
                module = ".".join(module_base + [file[:-2]])
                size = os.path.getsize(Path(root) / file)
                total_c += size
                append_result(f"build/{module}", "generated C", size, "B")
    append_result("build/.total", "generated C", total_c, "B")


def walk_lib_dir(project_directory: str):
    total_olean = 0
    ir_dir = Path.cwd() / project_directory / ".lake" / "build" / "lib" / "lean"
    for root, dirs, files in os.walk(ir_dir):
        module_base = root.split(f"{project_directory}/.lake/build/lib/lean")[1].split(
            "/"
        )[1:]
        for file in files:
            if file.endswith(".olean"):
                module = ".".join(module_base + [file[:-6]])
                size = os.path.getsize(Path(root) / file)
                total_olean += size
                append_result(f"build/{module}", "generated olean", size, "B")
    append_result("build/.total", "generated olean", total_olean, "B")


def checkout_project(
    verso_directory: Path,
    gitUrl: str,
    project_directory: str = "project",
    useO0: bool = False,
    branch: str = "main",
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
                        project_lean_version, verso_lean_version
                    )
        with open(lakefile, "w") as f:
            f.write("".join(lines))
        append_result("checkout", "success", 1)
        return True
    except Exception as e:
        print(e)
        append_result("checkout", "success", 0)
        return False


def project_build_default(project_directory: str) -> bool:
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
        append_result("build/default", "success", 1)
        return True
    except subprocess.SubprocessError as e:
        print(f"compilation failed {e}")
        append_result("build/default", "success", 0)
        return False
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("build/default", "success", 0)
        return False


def project_build_exe(project_directory: str, name: str) -> bool:
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
        append_result("build/exe", "success", 1)
        return True
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("build/exe", "success", 0)
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

# TODO if verso checkout contains bench/, use that
# TODO add TODO to remove bench code here

def main() -> None:
    global output_path
    global root
    global total_key_time
    global subtotals_key_time
    global cmdargs
    parser = argparse.ArgumentParser()

    # target and output are positional and defined by the Radar infrastructure
    # it just needs to be executable and it needs to take two arguments
    parser.add_argument(
        "target",
        type=Path,
        help="path to the Verso repo to be benchmarked",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="path the output file should be written to",
    )
    parser.add_argument(
        "-o", "--opt", type=str, help="optimization level o0 or no-opt-args"
    )
    parser.add_argument("-p", "--project", type=str, help="project")
    parser.add_argument("--skip-checkout", action="store_true")
    args = parser.parse_args()
    output_path = args.output
    use_o0_optimization = False
    if args.opt == "o0":
        use_o0_optimization = True
    elif args.opt is not None:
        print(f"unexpected opt level {args.opt}", file=sys.stderr)
        sys.exit(1)

    if args.project == "lean4cs1":
        binary = "build-doc"
        directory = "lean4-cs1"
        git_url = "https://github.com/robsimmons/Lean4CS1.git"
        git_branch = "verso"
        root = "lean4cs1"
        cmdargs = []
    elif args.project == "sherlock":
        binary = "sherlock"
        directory = "sherlock"
        git_url = "https://github.com/robsimmons/sherlock-lean.git"
        git_branch = "lean"
        root = "sherlock"
        cmdargs = []
    elif args.project == "refman":
        binary = "generate-manual"
        directory = "refman"
        git_url = "https://github.com/leanprover/reference-manual.git"
        git_branch = "main"
        root = "refman"
        cmdargs = ["--depth", "2", "--delay-html-multi", "multi.json"]
    else:
        print(f"unexpected project {args.project}", file=sys.stderr)
        sys.exit(1)

    if use_o0_optimization:
        root += "-o0"

    absolute_target = Path(os.path.abspath(args.target))

    if not args.skip_checkout:
        did_checkout = checkout_project(
            absolute_target,
            git_url,
            branch=git_branch,
            useO0=use_o0_optimization,
            project_directory=directory,
        )
    else:
        did_checkout = True

    if not did_checkout:
        print("checkout did not succeed")
        sys.exit(1)

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
    exe_size = os.path.getsize(
        Path.cwd() / directory / ".lake" / "build" / "bin" / binary
    )
    append_result("build/exe", "generated exe", exe_size, "B")
    start: float = time.time()
    subprocess.run(
        [f"./.lake/build/bin/{binary}"] + cmdargs,
        cwd=directory,
        check=True,
    )
    end: float = time.time()
    append_result("execute", "generation time", end - start, "s")

    for key, total in total_key_time.items():
        append_result("build/.total", f"{key} time", total, "s")
    for top_level_package, kv in subtotals_key_time.items():
        for key, total in kv.items():
            append_result(
                f"build/{top_level_package}/.total", f"{key} time", total, "s"
            )


if __name__ == "__main__":
    main()
