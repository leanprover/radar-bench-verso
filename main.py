#!/usr/bin/env python

import argparse
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

    # Arguments after -- are passed through to bench.py
    argv = sys.argv[1:]
    if "--" in argv:
        split_at = argv.index("--")
        argv, rest = argv[:split_at], argv[split_at + 1 :]
    else:
        rest = []
    args = parser.parse_args(argv)

    verso_dir = args.target.resolve()
    verso_bench_path = verso_dir / "bench" / "bench.py"
    if verso_bench_path.is_file():
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
