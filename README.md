# radar-bench-verso
Radar benchmarking for verso

All the scripts in this directory need to be called like this:

```
./bench-sherlock ../verso output-sherlock.txt
```

Where `../verso` can be replaced by another location where Verso already sits checked out and `output-sherlock.txt` is wherever you want the results to go.

The root of this repo will be the working directory when
the script starts.

## PR releases and local toolchains

The exact `lean-toolchain` from the Verso checkout is copied into the downstream
project. Releases from other Elan origins (including `lean4-nightly` and
`lean4-pr-releases`) and locally linked toolchains are supported.

Release and nightly names also select matching dependency refs automatically.
PR snapshot names and local aliases do not imply downstream Git refs, so their
existing dependency refs are retained unless `--dependency-version` is supplied.
That option selects the refs to use when rewriting dependencies; it does not
replace the actual toolchain. The selected dependencies must still compile with
the actual toolchain.

Only recognized release/nightly names from the project's old toolchain are used
as replacement keys. A local compiler alias such as `main` will not cause other
uses of `"main"` in the Lake file to be rewritten.

For example, benchmark a PR toolchain with a prepared nightly project branch:

```bash
./bench-refman-o0 ../verso-pr results.jsonl \
  --project-branch nightly-testing \
  --dependency-version nightly-2026-10-21
```

Both overrides are optional. A workload using `VERSO_LEAN_TOOLCHAIN` to select its
project branch requires an explicit branch or dependency version when the actual
toolchain has no inferable release/nightly ref. This avoids trying to clone a
branch named after a PR snapshot or local alias.

If the Verso revision contains its own `bench/bench.py`, overrides must appear in
that script's `--help` output. The wrapper rejects unsupported overrides before
starting the benchmark. Runs without overrides keep using older scripts as before.

Use separate scratch checkouts for benchmark runs: the harness cleans Verso's
build products, rewrites the downstream project, and edits its measured module.
