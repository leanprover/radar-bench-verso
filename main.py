#!/usr/bin/env python

import argparse
import json
import subprocess
from pathlib import Path
import re
from enum import Enum

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
                    lines[index] = f'require verso from "../{verso_directory}"'
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

    subprocess.check_output(
        ["lake", "update", "--no-ansi"], cwd="reference-manual", check=True
    )
    result = subprocess.run(
        ["lake", "build", "--no-ansi"], cwd="reference-manual", capture_output=True
    )
    if result.returncode == 0:
        append_result("compile", 1)
    else:
        append_result("compile", 0)

    print(result.stderr.decode("utf-8"))
    print(result.stdout.decode("utf-8"))


def main() -> None:
    global output_path
    parser = argparse.ArgumentParser()

    # target and output are positional and defined by the Radar infrastructure
    # it just needs to be executable and it needs to take two arguments
    parser.add_argument(
        "target",
        type=Path,
        help="path to the repo to be benchmarked",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="path the output file should be written to",
    )
    args = parser.parse_args()
    output_path = args.output

    prepare_reference_manual(args.target, CompileMatrixOption.O0)

    # locs = collect_locs(args.target)
    # count_and_output_locs(args.output, Path(), locs)
    append_result("test/awesome//loc", 0.99, "100%")
    append_result("test/suspiciousness//loc", 97, "%")


if __name__ == "__main__":
    main()
