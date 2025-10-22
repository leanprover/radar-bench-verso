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
root: str = "refman"

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


def walk_ir_dir():
    total_c = 0
    ir_dir = Path.cwd() / "reference-manual" / ".lake" / "build" / "ir"
    for root, dirs, files in os.walk(ir_dir):
        module_base = root.split("reference-manual/.lake/build/ir")[1].split("/")[1:]
        for file in files:
            if file.endswith(".c"):
                module = ".".join(module_base + [file[:-2]])
                size = os.path.getsize(Path(root) / file)
                total_c += size
                append_result(f"build/{module}", "generated C", size, "B")
    append_result(f"build/.total", "generated C", total_c, "B")


def walk_lib_dir():
    total_olean = 0
    ir_dir = Path.cwd() / "reference-manual" / ".lake" / "build" / "lib" / "lean"
    for root, dirs, files in os.walk(ir_dir):
        module_base = root.split("reference-manual/.lake/build/lib/lean")[1].split("/")[
            1:
        ]
        for file in files:
            if file.endswith(".olean"):
                module = ".".join(module_base + [file[:-6]])
                size = os.path.getsize(Path(root) / file)
                total_olean += size
                append_result(f"build/{module}", "generated olean", size, "B")
    append_result(f"build/.total", "generated olean", total_olean, "B")


class CompileMatrixOption(Enum):
    OCT_2025 = 1
    O0 = 2
    NO_ARGS = 3
    UNCHANGED = 4


def checkout_reference_manual(
    verso_directory: Path, option: CompileMatrixOption
) -> bool:
    try:
        with open(verso_directory / ".reference_manual_revision") as f:
            reference_manual_revision = "".join(
                [line for line in f.readlines() if not line.startswith("#")]
            ).strip()

        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "https://github.com/leanprover/reference-manual.git",
                f"--revision={reference_manual_revision}",
            ],
            capture_output=True,
            check=True,
        )

        lakefile: Path = Path.cwd() / "reference-manual" / "lakefile.lean"
        with open(lakefile) as f:
            lines = f.readlines()
            for index, line in enumerate(lines):
                if re.match(r"^require verso from ", line):
                    lines[index] = f'require verso from "{verso_directory}"'
                elif re.match(r"^([\s-])+moreLeancArgs := ", line):
                    if option == CompileMatrixOption.OCT_2025:
                        lines[index] = (
                            '  moreLeancArgs := #["-O0", "-mllvm", "-fast-isel", "-mllvm", "-fast-isel-abort=0"]\n'
                        )
                    elif option == CompileMatrixOption.O0:
                        lines[index] = '  moreLeancArgs := #["-O0"]\n'
                    elif option == CompileMatrixOption.NO_ARGS:
                        lines[index] = "\n"
        with open(lakefile, "w") as f:
            f.write("".join(lines))

        append_result("checkout", "success", 1)
        return True
    except Exception as e:  # noqa: E722
        print(e)
        append_result("checkout", "success", 0)
        return False


def compile_reference_manual() -> bool:
    try:
        subprocess.run(
            ["lake", "update", "--no-ansi"], cwd="reference-manual", check=True
        )
        start: float = time.time()
        result = subprocess.run(
            ["lake", "build", "--no-ansi"], cwd="reference-manual", capture_output=True
        )
        end: float = time.time()
        print(end - start)
        append_result("build/.total", "wall clock time", end - start, "s")
        process_output(result.stdout.decode("utf-8"))
        print(result.stderr.decode("utf-8"), file=sys.stderr)
        result.check_returncode()
        append_result("compile", "success", 1)
        return True
    except subprocess.SubprocessError as e:
        print(f"compilation failed {e}")
        append_result("compile", "success", 0)
        return False
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("compile", "success", 0)
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


def process_output(output: str):
    total_lean = 0.0
    totals: dict[str, float] = {}

    for line in output.split("\n"):
        match_val = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )
        if match_val:
            append_result(f"build/{match_val[3]}", "eval time", match_val[4])
            total_lean += parse_time(match_val[4])
            continue
        match_val = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+):([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )
        if match_val:
            append_result(f"build/{match_val[3]}", f"{match_val[4]} time", match_val[5])
            prev_total = totals.get(match_val[4], 0.0)
            totals[match_val[4]] = prev_total + parse_time(match_val[5])
            continue
        match_val = re.match(r"[^]]*\]\s*Built", line)
        if match_val:
            print(f"MISSED?: {line}", file=sys.stderr)
        else:
            print(line)

    append_result("build/.total", "eval time", total_lean, "s")
    for key, total in totals.items():
        append_result("build/.total", f"{key} time", total, "s")


def main() -> None:
    global output_path
    global root
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
        "-o", "--opt", type=str, help="optimization level (O0, oct2025, or none)"
    )
    parser.add_argument("--skip-checkout", action="store_true")
    args = parser.parse_args()
    output_path = args.output
    # opt_level = CompileMatrixOption.UNCHANGED
    opt_level: CompileMatrixOption = CompileMatrixOption.UNCHANGED
    if args.opt == "O0":
        opt_level = CompileMatrixOption.O0
    elif args.opt == "oct2025":
        opt_level = CompileMatrixOption.OCT_2025
    elif args.opt == "none":
        opt_level = CompileMatrixOption.NO_ARGS
    elif args.opt is not None:
        print(f"unexpected opt level {args.opt}", file=sys.stderr)
        sys.exit(1)

    if opt_level == CompileMatrixOption.O0:
        root = "refman-o0"
    elif opt_level == CompileMatrixOption.UNCHANGED:
        root = "refman-unchnaged"
    elif opt_level == CompileMatrixOption.NO_ARGS:
        root = "refman-no-opt-args"
    elif opt_level == CompileMatrixOption.OCT_2025:
        root = "refman-opt-oct-2025"
    else:
        root = "refman-other"

    absolute_target = Path(os.path.abspath(args.target))

    if not args.skip_checkout:
        did_checkout = checkout_reference_manual(absolute_target, opt_level)
    else:
        did_checkout = True

    if did_checkout:
        did_compile = compile_reference_manual()
    else:
        did_compile = False

    if did_compile:
        walk_ir_dir()
        walk_lib_dir()
        exe_size = os.path.getsize(
            Path.cwd()
            / "reference-manual"
            / ".lake"
            / "build"
            / "bin"
            / "generate-manual"
        )
        append_result("build/«generate-manual»", "generated exe", exe_size, "B")
        start: float = time.time()
        subprocess.run(
            ["./.lake/build/bin/generate-manual", "--depth", "2"],
            cwd="reference-manual/",
            check=True,
        )
        end: float = time.time()
        append_result("execute", "generation time", end - start, "s")

    else:
        print("signaling failure exit")
        sys.exit(1)

    # locs = collect_locs(args.target)
    # count_and_output_locs(args.output, Path(), locs)


if __name__ == "__main__":
    main()
