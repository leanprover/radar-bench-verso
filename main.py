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

output_path: Path


def append_result(metric: str, value: str | float | int, unit=None) -> None:
    global output_path
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

    print(f"{metric} -> {val}{f'({unit})' if unit else ''}")
    with open(output_path, "a") as f:
        f.write(json.dumps({"metric": metric, "value": val, "unit": unit}) + "\n")


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

        append_result("checkout", 1)
        return True
    except Exception as e:  # noqa: E722
        print(e)
        append_result("checkout", 0)
        return False

def compile_reference_manual():
    try:
        subprocess.run(
            ["lake", "update", "--no-ansi"], cwd="reference-manual", check=True
        )
        start = time.time()
        result = subprocess.run(
            ["lake", "build", "--no-ansi"], cwd="reference-manual", capture_output=True
        )
        end: float = time.time()
        print(end - start)
        append_result("build/total/wall", end - start)
        process_output(result.stdout.decode("utf-8"))
        print(result.stderr.decode("utf-8"), file=sys.stderr)
        result.check_returncode()
        append_result("compile", 1)
    except subprocess.SubprocessError as e:
        print(f"compilation failed {e}")
        append_result("compile", 0)
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("compile", 0)


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
            append_result(f"build/single/{match_val[3]}/lean/time", match_val[4])
            total_lean += parse_time(match_val[4])
            continue
        match_val = re.match(
            r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.\-/_«»]+):([A-Za-z0-9.\-/_«»]+) \(([A-Za-z0-9.]+)\)$",
            line,
        )
        if match_val:
            append_result(f"build/single/{match_val[3]}/{match_val[4]}/time", match_val[5])
            prev_total = totals.get(match_val[4], 0.0)
            totals[match_val[4]] = prev_total + parse_time(match_val[5])
            continue
        match_val = re.match(r"[^]]*\]\s*Built", line)
        if match_val:
            print(f"MISSED?: {line}", file=sys.stderr)
        else:
            print(line)

    append_result("build/total/lean", total_lean, "s")
    for key, total in enumerate(totals.items()):
        append_result(f"build/total/{key}", total, "s")

def main() -> None:
    global output_path
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
    parser.add_argument(
        "--skip-checkout", action='store_true'
    )
    args = parser.parse_args()
    output_path = args.output
    # opt_level = CompileMatrixOption.UNCHANGED
    opt_level: CompileMatrixOption = CompileMatrixOption.O0
    if args.opt == "O0":
        opt_level = CompileMatrixOption.O0
    elif args.opt == "oct2025":
        opt_level = CompileMatrixOption.OCT_2025
    elif args.opt == "none":
        opt_level = CompileMatrixOption.NO_ARGS
    elif args.opt is not None:
        print(f"unexpected opt level {args.opt}", file=sys.stderr)
        sys.exit(1)

    absolute_target = Path(os.path.abspath(args.target))

    if (not args.skip_checkout):
        did_checkout = checkout_reference_manual(absolute_target, opt_level)
    else:
        did_checkout = True

    if (did_checkout):
        did_compile = compile_reference_manual()
    else:
        append_result("compile", 0)
        did_compile = False

    if (not did_compile):
        sys.exit(1)

    # locs = collect_locs(args.target)
    # count_and_output_locs(args.output, Path(), locs)


if __name__ == "__main__":
    main()
