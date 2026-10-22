#!/usr/bin/env python

import argparse
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()

    # target and output are positional and defined by the Radar infrastructure
    # this script just needs to be executable and it needs to take two arguments
    parser.add_argument(
        "target",
        type=Path,
        help="path to the Verso repo to be benchmarked",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="file the measurements should be appended to (created if missing)",
    )
    parser.add_argument("--project-branch", help="override the workload's project branch/tag")
    parser.add_argument("--dependency-version", help="override the release/nightly ref for dependencies")

    # Arguments after -- are passed through to bench.py
    argv = sys.argv[1:]
    if "--" in argv:
        split_at = argv.index("--")
        argv, rest = argv[:split_at], argv[split_at + 1 :]
    else:
        rest = []
    args = parser.parse_args(argv)
    # Explicit wrapper arguments override the workload defaults after `--`.
    overrides = (
        ("--project-branch", args.project_branch),
        ("--dependency-version", args.dependency_version),
    )
    required_options = set()
    for option, value in overrides:
        if value is not None:
            rest += [option, value]
            required_options.add(option)
    # Also check the new option when supplied directly after `--`.
    if any(arg.partition("=")[0] == "--dependency-version" for arg in rest):
        required_options.add("--dependency-version")

    verso_dir = args.target.resolve()
    verso_bench_path = verso_dir / "bench" / "bench.py"
    if verso_bench_path.is_file():
        if required_options:
            # Older revision-local scripts may ignore unknown arguments and still
            # report success. Check their CLI before starting any benchmark work.
            try:
                help_result = subprocess.run(
                    [sys.executable, str(verso_bench_path), "--help"],
                    capture_output=True, text=True, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired) as e:
                parser.error(f"Cannot check options supported by {verso_bench_path}: {e}")
            if help_result.returncode != 0:
                parser.error(f"Cannot check {verso_bench_path} with --help; no benchmark was started")
            supported = set(re.findall(r"--[a-zA-Z][a-zA-Z0-9-]*", help_result.stdout))
            if missing := required_options - supported:
                parser.error(
                    f"{verso_bench_path} does not advertise {', '.join(sorted(missing))}; "
                    "update that script or omit these overrides"
                )
        result = subprocess.run(
            [sys.executable, str(verso_bench_path), str(args.output)] + rest,
        )
    else:
        parent_dir = Path(__file__).resolve().parent
        result = subprocess.run(
            [sys.executable, str(parent_dir / "bench.py"), str(args.output), "--verso-dir", str(verso_dir)] + rest,
        )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
