#!/usr/bin/env python

import os.path
import argparse
import json
import subprocess
from pathlib import Path
import re
from enum import Enum
import time
import sys
from typing import Any

output_path: Path
root: str


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

        match_val = re.match(r"([0-9.]+)%", val)
        if match_val:
            val = match_val[1]
            unit = "%"

        # Supported: s for sec, B for bytes
        match_val = re.match(r"([0-9.]+)([a-zA-Z]+)", val)
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
                print(
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
            if not versos_lean_toolchain.startswith("leanprover/lean4:"):
                print(
                    f"lean toolchain for project isn't a lean4 version: {project_lean_toolchain}"
                )
            project_lean_version = project_lean_toolchain[17:]
        with open(Path.cwd() / project_directory / "lean-toolchain", "w") as f:
            f.write(versos_lean_toolchain)

        lakefile: Path = Path.cwd() / project_directory / "lakefile.lean"
        with open(lakefile) as f:
            lines = f.readlines()
            count = 0
            for index, line in enumerate(lines):
                count += 1
                if re.match(r"^require verso from ", line):
                    lines[index] = f'require verso from "{verso_directory}"'
                elif re.match(r"^package", line) and useO0:
                    lines[index] = line + '  moreLeancArgs := #["-O0"]\n'
                else:
                    lines[index] = line.replace(
                        project_lean_version, verso_lean_version
                    )
        with open(lakefile, "w") as f:
            f.write("".join(lines))
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
        subprocess.run
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
        return float(match_val[1]) / 100
    match_val = re.match(r"([0-9.]+)s$", time)
    if match_val:
        return float(match_val[1])
    print(f"cannot parse time {time}")
    raise Exception("Cannot parse time")


total_eval_time: float = 0
total_key_time: dict[str, float] = {}


def process_output(prefix: str, output: str):
    global total_eval_time
    global total_key_time

    total_lean = 0.0
    totals: dict[str, float] = {}

    for line in output.split("\n"):
        match_val = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )
        if match_val:
            append_result(f"{prefix}/{match_val[3]}", "eval time", match_val[4])
            total_lean += parse_time(match_val[4])
            continue
        match_val = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+):([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )
        if match_val:
            append_result(
                f"{prefix}/{match_val[3]}", f"{match_val[4]} time", match_val[5]
            )
            prev_total = totals.get(match_val[4], 0.0)
            totals[match_val[4]] = prev_total + parse_time(match_val[5])
            continue
        match_val = re.match(r"[^]]*\]\s*Built", line)
        if match_val:
            print(f"MISSED?: {line}", file=sys.stderr)
        else:
            print(line)

    append_result(f"{prefix}/.total", "eval time", total_lean, "s")
    total_eval_time += total_lean
    for key, total in totals.items():
        if key not in total_key_time:
            total_key_time[key] = 0
        total_key_time[key] += total
        append_result(f"{prefix}/.total", f"{key} time", total, "s")


def main() -> None:
    global output_path
    global root
    global total_eval_time
    global total_key_time
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
        "-o", "--opt", type=str, help="optimization level o0 or no-opt-args)"
    )
    parser.add_argument("-p", "--project", type=str, help="project)")
    parser.add_argument("--skip-checkout", action="store_true")
    args = parser.parse_args()
    output_path = args.output
    use_o0_optimization = False
    if args.opt == "o0":
        opt_level = True
    elif args.opt is not None:
        print(f"unexpected opt level {args.opt}", file=sys.stderr)
        sys.exit(1)

    if args.project == "lean4cs1":
        binary = "build-doc"
        directory = "lean4-cs1"
        git_url = "https://github.com/robsimmons/Lean4CS1.git"
        git_branch = "verso"
        root = "lean4cs1"
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

    if did_checkout:
        did_build = project_build_default(directory)
    else:
        print("build step did not succeed")
        did_build = False

    if did_build:
        print("exe build step did not succeed")
        did_compile = project_build_exe(directory, binary)
    else:
        did_compile = False

    if did_compile:
        walk_ir_dir(directory)
        walk_lib_dir(directory)
        exe_size = os.path.getsize(
            Path.cwd() / directory / ".lake" / "build" / "bin" / binary
        )
        append_result("build/exe", "generated exe", exe_size, "B")
        start: float = time.time()
        subprocess.run(
            [f"./.lake/build/bin/{binary}"],
            cwd=directory,
            check=True,
        )
        end: float = time.time()
        append_result("execute", "generation time", end - start, "s")

        append_result("build/.total", "eval time", total_eval_time, "s")
        for key, total in total_key_time.items():
            append_result("build/.total", f"{key} time", total, "s")

    else:
        print("signaling failure exit")
        sys.exit(1)


if __name__ == "__main__":
    main()
