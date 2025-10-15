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
            val = match_val.get[1]
            unit = "%"

        # Supported: s for sec, B for bytes
        match_val = re.match(r"([0-9.]+)([a-zA-Z]+)", val)
        if match_val:
            val = match_val.get[1]
            unit = match_val.get[2]

    print(f"{metric} -> {val}{f'({unit})' if unit else ''}")
    with open(output_path, "a") as f:
        f.write(json.dumps({"metric": metric, "value": val, "unit": unit}) + "\n")


class CompileMatrixOption(Enum):
    OCT_2025 = 1
    O0 = 2
    NO_ARGS = 3
    UNCHANGED = 4


def prepare_reference_manual(
    verso_directory: Path, option: CompileMatrixOption
) -> None:
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
                            '  moreLeancArgs := #["-O0", "-mllvm", "-fast-isel", "-mllvm", "-fast-isel-abort=0"]'
                        )
                    elif option == CompileMatrixOption.O0:
                        lines[index] = '  moreLeancArgs := #["-O0"]'
                    elif option == CompileMatrixOption.NO_ARGS:
                        lines[index] = ""
        with open(lakefile, "w") as f:
            f.write("".join(lines))

        append_result("checkout", 1)
    except Exception as e:  # noqa: E722
        print(e)
        append_result("checkout", 0)
        append_result("compile", 0)
        print("Cannot check out reference manual")
        return False

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
        print(result.stderr.decode("utf-8"))
        if result.returncode != 0:
            print(result.stdout.decode("utf-8"))
            print(result.stderr.decode("utf-8"))
        result.check_returncode()
        append_result("compile", 1)
    except subprocess.SubprocessError as e:
        print(f"compilation failed {e}")
        append_result("compile", 0)
    except Exception as e:
        print(f"unexpected error {e}")
        append_result("compile", 0)


def parse_time(str: str):
    match_val = re.match(r"^([0-9]+)ms$")
    if (match_val):
        return float(re[1]) / 100
    match_val = re.match(r"^([0-9]+)s$")
    if (match_val):
        return float(re[1])
    print(f"cannot parse time {str}")
    raise Exception("Cannot parse time")


def process_output(output: str):
    total_lean = 0.0
    total_object = 0.0

    for line in str.split("\n"):
        match_val = re.match(r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.-]+) \(([A-Za-z0-9.]+)\)$", line)
        if match_val:
            append_result(f"build/single/{re[3]}/lean/time", re[4])
            total_lean += parse_time(re[4])
            print(f"built {re[3]} in {re[4]}")
            continue
        match_val = re.match(r"^. \[([0-9]+)/([0-9]+)\] Built ([A-Za-z0-9.-]+):c.o \(([A-Za-z0-9.]+)\)$", line)
        if match_val:
            append_result(f"build/single/{re[3]}/ir/time", re[4])
            total_object += parse_time(re[4])
            print(f"compiled {re[3]} in {re[4]}")
            continue
        match_val = re.match(r"\[[^.]*\]\s*Built")
        if match_val:
           print(f"MISSED?: {line}", file=sys.stderr)

    append_result("build/total/lean", {total_lean})
    append_result("build/total/object", {total_lean})


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
    parser.add_argument("-o", "--opt", type=str, help="optimization level (O0, oct2025, or none)")
    args = parser.parse_args()
    output_path = args.output
    opt_level = CompileMatrixOption.UNCHANGED
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

    prepare_reference_manual(absolute_target, opt_level)

    # locs = collect_locs(args.target)
    # count_and_output_locs(args.output, Path(), locs)
    append_result("test/awesome//loc", 0.99, "100%")
    append_result("test/suspiciousness//loc", 97, "%")


if __name__ == "__main__":
    main()
