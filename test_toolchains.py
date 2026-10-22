import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bench


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "lean-toolchain").write_text("leanprover/lean4:v4.36.0-rc1\n")
        (self.source / "lakefile.lean").write_text(
            'import Lake\nopen Lake DSL\npackage demo where\n'
            'require verso from git "https://github.com/leanprover/verso" @ "v4.36.0-rc1"\n'
            'require subverso from git "https://github.com/leanprover/subverso" @ "v4.36.0-rc1"\n'
        )
        self.git("init", "-b", "fixture")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgSign", "false")
        (self.source / "branch.txt").write_text("fixture")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        for branch in ("v4.36.0-rc1", "nightly-2026-10-21"):
            self.git("switch", "-c", branch)
            (self.source / "branch.txt").write_text(branch)
            self.git("commit", "-am", branch)
        self.git("switch", "fixture")
        self.verso = self.root / "verso"
        self.verso.mkdir()
        globals_patch = patch.multiple(
            bench, output_path=self.root / "measurements.jsonl", root="test", create=True
        )
        globals_patch.start()
        self.addCleanup(globals_patch.stop)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.source, check=True, capture_output=True)

    def checkout(self, toolchain, branch="fixture", dependency_version=None):
        (self.verso / "lean-toolchain").write_text(toolchain + "\n")
        project = self.root / "project"
        self.errors = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(self.errors):
            result = bench.checkout_project(
                self.verso, self.source.as_uri(), project, False, branch, dependency_version
            )
        return result, project

    def test_release_and_both_nightly_origins(self):
        for selector, ref in (
            ("leanprover/lean4:v4.36.0-rc1", "v4.36.0-rc1"),
            ("leanprover/lean4:nightly-2026-10-21", "nightly-2026-10-21"),
            ("leanprover/lean4-nightly:nightly-2026-10-21", "nightly-2026-10-21"),
        ):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as dst:
                bench.output_path = Path(dst) / "measurements.jsonl"
                (self.verso / "lean-toolchain").write_text(selector + "\n")
                project = Path(dst) / "project"
                with contextlib.redirect_stdout(io.StringIO()):
                    result = bench.checkout_project(
                        self.verso, self.source.as_uri(), project, False, bench.VERSO_LEAN_TOOLCHAIN_MAGIC
                    )
                self.assertEqual(result, (True, False))
                self.assertEqual((project / "lean-toolchain").read_text(), selector)
                self.assertEqual((project / "branch.txt").read_text(), ref)
                self.assertIn(f'@ "{ref}"', (project / "lakefile.lean").read_text())

    def test_pr_snapshot_preserves_dependency_refs(self):
        selector = "leanprover/lean4-pr-releases:pr-release-15856-87576ac"
        result, project = self.checkout(selector)
        self.assertEqual(result, (True, False))
        self.assertEqual((project / "lean-toolchain").read_text(), selector)
        lakefile = (project / "lakefile.lean").read_text()
        self.assertIn(f'require verso from "{self.verso}"', lakefile)
        self.assertIn('@ "v4.36.0-rc1"', lakefile)
        self.assertNotIn('@ "pr-release-', lakefile)

    def test_dependency_override_does_not_replace_actual_toolchain(self):
        selector = "leanprover/lean4-pr-releases:pr-release-15856-87576ac"
        result, project = self.checkout(selector, bench.VERSO_LEAN_TOOLCHAIN_MAGIC, "nightly-2026-10-21")
        self.assertEqual(result, (True, False))
        self.assertEqual((project / "lean-toolchain").read_text(), selector)
        self.assertIn('@ "nightly-2026-10-21"', (project / "lakefile.lean").read_text())
        self.assertEqual((project / "branch.txt").read_text(), "nightly-2026-10-21")

    def test_explicit_branch_is_independent_of_dependency_version(self):
        result, project = self.checkout("local-lean", "fixture", "nightly-2026-10-21")
        self.assertEqual(result, (True, False))
        self.assertEqual((project / "branch.txt").read_text(), "fixture")
        self.assertIn('@ "nightly-2026-10-21"', (project / "lakefile.lean").read_text())

    def test_downstream_local_alias_does_not_rewrite_unrelated_strings(self):
        (self.source / "lean-toolchain").write_text("main\n")
        lakefile = self.source / "lakefile.lean"
        lakefile.write_text(lakefile.read_text() +
            'require other from git "https://example.invalid/other" @ "main"\n'
            'def channel := "main"\n')
        self.git("add", ".")
        self.git("commit", "-m", "use local compiler")
        result, project = self.checkout("local-candidate", "fixture", "v4.36.0-rc1")
        self.assertEqual(result, (True, False))
        rewritten = (project / "lakefile.lean").read_text()
        self.assertIn('require other from git "https://example.invalid/other" @ "main"', rewritten)
        self.assertIn('def channel := "main"', rewritten)
        self.assertIn(f'require verso from "{self.verso}"', rewritten)

    def test_local_toolchain_is_not_a_dependency_ref(self):
        result, project = self.checkout("my-local-lean")
        self.assertEqual(result, (True, False))
        self.assertEqual((project / "lean-toolchain").read_text(), "my-local-lean")
        self.assertIn('@ "v4.36.0-rc1"', (project / "lakefile.lean").read_text())

    def test_custom_toolchain_requires_explicit_magic_branch(self):
        result, project = self.checkout("my-local-lean", bench.VERSO_LEAN_TOOLCHAIN_MAGIC)
        self.assertEqual(result, (False, False))
        self.assertFalse(project.exists())
        self.assertIn("--project-branch", self.errors.getvalue())
        self.assertIn("--dependency-version", self.errors.getvalue())
        self.assertEqual(json.loads(bench.output_path.read_text())["value"], "0")

    def test_downstream_toolchain_can_have_another_origin(self):
        (self.source / "lean-toolchain").write_text("leanprover/lean4-nightly:nightly-2026-10-20\n")
        lakefile = self.source / "lakefile.lean"
        lakefile.write_text(lakefile.read_text().replace('v4.36.0-rc1', 'nightly-2026-10-20'))
        self.git("add", ".")
        self.git("commit", "-m", "nightly")
        selector = "leanprover/lean4:v4.36.0-rc1"
        result, project = self.checkout(selector)
        self.assertEqual(result, (True, False))
        self.assertEqual((project / "lean-toolchain").read_text(), selector)
        self.assertIn('@ "v4.36.0-rc1"', (project / "lakefile.lean").read_text())
        self.assertNotIn('nightly-2026-10-20', (project / "lakefile.lean").read_text())


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "bench").mkdir()
        self.script = self.root / "bench" / "bench.py"

    def write_harness(self, supports_dependency_version):
        self.script.write_text(
            "import argparse, json\nfrom pathlib import Path\n"
            "p = argparse.ArgumentParser()\np.add_argument('output')\n"
            "p.add_argument('--project-branch')\n" +
            ("p.add_argument('--dependency-version')\n" if supports_dependency_version else "") +
            "args, unknown = p.parse_known_args()\n"
            "Path(__file__).with_name('started').touch()\n"
            "print(json.dumps(vars(args)))\n"
        )

    def run_wrapper(self, *args):
        return subprocess.run(
            [sys.executable, str(Path(__file__).with_name("main.py")), str(self.root), "out.jsonl", *args],
            capture_output=True, text=True,
        )

    def test_overrides_reach_revision_local_harness_after_workload_defaults(self):
        self.write_harness(True)
        result = self.run_wrapper(
            "--project-branch", "fixture", "--dependency-version", "v4.36.0-rc1", "--",
            "--project-branch", bench.VERSO_LEAN_TOOLCHAIN_MAGIC,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["project_branch"], "fixture")
        self.assertEqual(json.loads(result.stdout)["dependency_version"], "v4.36.0-rc1")

    def test_legacy_harness_rejects_unsupported_override_before_starting(self):
        self.write_harness(False)
        result = self.run_wrapper("--dependency-version", "nightly-2026-10-21")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--dependency-version", result.stderr)
        self.assertFalse(self.script.with_name("started").exists())

    def test_pass_through_override_is_also_checked(self):
        self.write_harness(False)
        result = self.run_wrapper("--", "--dependency-version=nightly-2026-10-21")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--dependency-version", result.stderr)
        self.assertFalse(self.script.with_name("started").exists())

    def test_legacy_harness_can_still_honor_supported_override(self):
        self.write_harness(False)
        result = self.run_wrapper(
            "--project-branch", "fixture", "--", "--project-branch", "old-default"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["project_branch"], "fixture")

    def test_unverifiable_harness_fails_before_starting(self):
        self.script.write_text(
            "import sys\nfrom pathlib import Path\n"
            "if '--help' in sys.argv: raise SystemExit(42)\n"
            "Path(__file__).with_name('started').touch()\n"
        )
        result = self.run_wrapper("--project-branch", "fixture")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--help", result.stderr)
        self.assertFalse(self.script.with_name("started").exists())

    def test_ordinary_legacy_run_needs_no_help_support(self):
        self.script.write_text(
            "import sys\n"
            "if '--help' in sys.argv: raise SystemExit(42)\n"
            "print('legacy run')\n"
        )
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "legacy run")


if __name__ == "__main__":
    unittest.main()
