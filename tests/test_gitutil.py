from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TempDirCase  # first: puts <template>/_meta on sys.path
from brainlib import gitutil


class GitUtilCase(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        # gitutil runs git in this process: give it the isolated environment too, so the person's global
        # git config (signing, init.defaultBranch, diff.ignoreSubmodules, ...) never reaches a test.
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def repo(self, label="repo") -> Path:
        """An empty repository on `main` inside the `with space` temp dir."""
        path = self._new_dir(label)
        self.git(path, "init", "-q")
        self.git(path, "symbolic-ref", "HEAD", "refs/heads/main")
        return path

    def commit(self, repo: Path, rel: str, text: str = "x\n", message: str = "c", mode=None) -> None:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if mode is not None:
            os.chmod(target, mode)
        self.git(repo, "add", "--", rel)
        self.git(repo, "commit", "-q", "-m", message)

    def stage(self, repo: Path, rel: str, data: bytes = b"x\n") -> None:
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.git(repo, "add", "-f", "--", rel)


class GitRunnerTest(GitUtilCase):
    def test_runs_in_the_isolated_environment(self):
        self.assertEqual(os.environ["HOME"], self.env["HOME"])
        self.assertEqual(gitutil.git(self._new_dir("plain"), "config", "--global", "--list").strip(), "")

    def test_returns_text_and_bytes(self):
        repo = self.repo()
        self.assertEqual(gitutil.git(repo, "rev-parse", "--is-inside-work-tree"), "true\n")
        raw = gitutil.git(repo, "rev-parse", "--is-inside-work-tree", binary=True)
        self.assertIsInstance(raw, bytes)
        self.assertEqual(raw, b"true\n")

    def test_failure_raises_with_stderr_and_check_false_returns_output(self):
        plain = self._new_dir("plain")
        with self.assertRaises(gitutil.GitError) as caught:
            gitutil.git(plain, "rev-parse", "--git-dir")
        self.assertIn("not a git repository", str(caught.exception))
        self.assertIn("not a git repository", caught.exception.stderr)
        self.assertEqual(gitutil.git(plain, "rev-parse", "--git-dir", check=False), "")

    def test_a_missing_directory_is_a_git_error(self):
        with self.assertRaises(gitutil.GitError):
            gitutil.git(self.tmp / "nowhere", "status")

    def test_arguments_are_never_interpreted_by_a_shell(self):
        repo = self.repo()
        nasty = "a b; touch pwned; $(touch pwned2)"
        gitutil.git(repo, "config", "brain.test", nasty)
        self.assertEqual(gitutil.git(repo, "config", "--get", "brain.test").rstrip("\n"), nasty)
        self.assertFalse((repo / "pwned").exists() or (repo / "pwned2").exists())

    def test_status_does_not_take_optional_locks(self):
        # Plain `git status` rewrites the index to refresh stat data; --no-optional-locks must not.
        repo = self.repo()
        self.commit(repo, "a.txt")
        os.utime(repo / "a.txt", (1_000_000_000, 1_000_000_000))  # content unchanged, stat data stale
        before = (repo / ".git" / "index").read_bytes()
        gitutil.git(repo, "status", "--short")
        self.assertEqual((repo / ".git" / "index").read_bytes(), before)
        subprocess.run(["git", "status", "--short"], cwd=str(repo), env=self.env, capture_output=True)
        self.assertNotEqual((repo / ".git" / "index").read_bytes(), before, "the control did not refresh the index")


class RepoTest(GitUtilCase):
    def test_is_repo(self):
        repo = self.repo()
        sub = repo / "docs"
        sub.mkdir()
        plain = self._new_dir("plain")
        self.assertTrue(gitutil.is_repo(repo))
        self.assertFalse(gitutil.is_repo(sub), "a folder inside a repo is not itself a repo")
        self.assertFalse(gitutil.is_repo(plain))
        self.assertFalse(gitutil.is_repo(self.tmp / "nowhere"))

    def test_is_repo_for_a_linked_worktree(self):
        repo = self.repo()
        self.commit(repo, "a.txt")
        wt = self._new_dir("wt")
        wt.rmdir()
        self.git(repo, "worktree", "add", "-q", str(wt))
        self.assertTrue((wt / ".git").is_file())
        self.assertTrue(gitutil.is_repo(wt))


class StagedTest(GitUtilCase):
    def test_staged_lists_added_and_modified_not_deleted(self):
        repo = self.repo()
        self.commit(repo, "old.txt")
        self.commit(repo, "gone.txt")
        self.stage(repo, "docs/new file.md")
        self.stage(repo, "old.txt", b"changed\n")
        self.git(repo, "rm", "-q", "gone.txt")
        self.assertEqual(gitutil.staged(repo), ["docs/new file.md", "old.txt"])

    def test_staged_in_an_unborn_repo_and_when_empty(self):
        repo = self.repo()
        self.assertEqual(gitutil.staged(repo), [])
        self.stage(repo, "a.txt")
        self.assertEqual(gitutil.staged(repo), ["a.txt"])

    def test_staged_keeps_odd_names_exact(self):
        repo = self.repo()
        for name in ("tab\there.md", "new\nline.md", "café.md", "-dash.md"):
            self.stage(repo, name)
        self.assertEqual(sorted(gitutil.staged(repo)), sorted(["tab\there.md", "new\nline.md", "café.md", "-dash.md"]))

    def test_staged_blob_is_the_staged_content_not_the_working_tree(self):
        repo = self.repo()
        self.stage(repo, "docs/a b.md", b"staged\n")
        (repo / "docs" / "a b.md").write_bytes(b"edited after staging\n")
        self.assertEqual(gitutil.staged_blob(repo, "docs/a b.md"), b"staged\n")
        self.assertEqual(gitutil.staged_size(repo, "docs/a b.md"), 7)

    def test_staged_blob_of_a_missing_path_is_a_git_error(self):
        repo = self.repo()
        with self.assertRaises(gitutil.GitError):
            gitutil.staged_blob(repo, "nope.md")

    def test_staged_blob_reads_binary_exactly(self):
        repo = self.repo()
        data = bytes(range(256)) * 3
        self.stage(repo, "bin.dat", data)
        self.assertEqual(gitutil.staged_blob(repo, "bin.dat"), data)

    def test_staged_entries_give_status_and_mode_including_deletions_and_gitlinks(self):
        repo = self.repo()
        self.commit(repo, "gone.txt")
        self.commit(repo, "moved.txt", "content that is long enough to be recognised as a rename\n")
        self.stage(repo, "new.txt")
        self.git(repo, "rm", "-q", "gone.txt")
        self.git(repo, "mv", "moved.txt", "renamed.txt")
        inner = repo / "docs" / "inner"
        inner.mkdir(parents=True)
        self.git(inner, "init", "-q")
        self.git(inner, "commit", "-q", "--allow-empty", "-m", "i")
        subprocess.run(["git", "add", "-f", "docs/inner"], cwd=str(repo), env=self.env, capture_output=True, check=True)
        found = {e.path: (e.status, e.mode) for e in gitutil.staged_entries(repo)}
        self.assertEqual(found["new.txt"], ("A", "100644"))
        self.assertEqual(found["gone.txt"][0], "D")
        self.assertEqual(found["renamed.txt"][0], "A")  # renames are reported as a delete and an add
        self.assertEqual(found["moved.txt"][0], "D")
        self.assertEqual(found["docs/inner"], ("A", "160000"))


class IgnoreSubmodulesConfigTest(GitUtilCase):
    def test_staged_lists_see_a_gitlink_whatever_diff_ignoresubmodules_says(self):
        repo = self.repo()
        self.git(repo, "config", "diff.ignoreSubmodules", "all")
        inner = repo / "inner"
        inner.mkdir()
        self.git(inner, "init", "-q")
        self.git(inner, "commit", "-q", "--allow-empty", "-m", "i")
        subprocess.run(["git", "add", "-f", "inner"], cwd=str(repo), env=self.env, capture_output=True, check=True)
        self.assertEqual(gitutil.staged(repo), ["inner"])
        self.assertEqual([(e.path, e.mode) for e in gitutil.staged_entries(repo)], [("inner", "160000")])


class NestedReposTest(GitUtilCase):
    def test_finds_repos_at_any_depth_and_does_not_descend(self):
        root = self.repo("outer")
        (root / "a" / "b").mkdir(parents=True)
        inner = root / "a" / "b" / "inner"
        inner.mkdir()
        self.git(inner, "init", "-q")
        deeper = inner / "vendor" / "deep"
        deeper.mkdir(parents=True)
        self.git(deeper, "init", "-q")
        top = root / "top"
        top.mkdir()
        self.git(top, "init", "-q")
        (root / "plain").mkdir()
        self.assertEqual(gitutil.nested_repos(root), [inner, top])

    def test_a_git_file_marks_a_repo_too(self):
        root = self.repo("outer")
        self.commit(root, "a.txt")
        wt = root / "trees" / "wt"
        self.git(root, "worktree", "add", "-q", str(wt))
        self.assertTrue((wt / ".git").is_file())
        self.assertEqual(gitutil.nested_repos(root), [wt])

    def test_skips_the_roots_own_git_and_symlinked_dirs(self):
        root = self.repo("outer")
        elsewhere = self.repo("elsewhere")
        (root / "link").symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(gitutil.nested_repos(root), [])

    def test_a_root_that_is_not_a_repo_still_lists_the_repos_below_it(self):
        root = self._new_dir("folder")
        inner = root / "one"
        inner.mkdir()
        self.git(inner, "init", "-q")
        self.assertEqual(gitutil.nested_repos(root), [inner])

    def test_read_only_calls_leave_a_nested_index_untouched(self):
        root = self.repo("outer")
        inner = root / "inner"
        inner.mkdir()
        self.git(inner, "init", "-q")
        self.git(inner, "symbolic-ref", "HEAD", "refs/heads/main")
        self.commit(inner, "a.txt")
        os.utime(inner / "a.txt", (1_000_000_000, 1_000_000_000))
        before = (inner / ".git" / "index").read_bytes()
        gitutil.nested_repos(root)
        gitutil.repo_state(inner)
        gitutil.short_sha(inner)
        gitutil.default_branch(inner)
        gitutil.is_repo(inner)
        self.assertEqual((inner / ".git" / "index").read_bytes(), before)


class RepoStateTest(GitUtilCase):
    def test_no_commits_no_remote(self):
        self.assertEqual(gitutil.repo_state(self.repo()), gitutil.RepoState(False, 0))

    def test_commits_without_a_remote_are_all_unpushed(self):
        repo = self.repo()
        self.commit(repo, "a.txt")
        self.commit(repo, "b.txt")
        self.assertEqual(gitutil.repo_state(repo), gitutil.RepoState(False, 2))

    def test_pushed_and_then_ahead(self):
        repo = self.repo()
        self.commit(repo, "a.txt")
        remote = self._new_dir("remote.git")
        self.git(remote, "init", "-q", "--bare")
        self.git(repo, "remote", "add", "origin", str(remote))
        self.git(repo, "push", "-q", "origin", "main")
        self.assertEqual(gitutil.repo_state(repo), gitutil.RepoState(True, 0))
        self.commit(repo, "b.txt")
        self.assertEqual(gitutil.repo_state(repo), gitutil.RepoState(True, 1))

    def test_a_remote_with_nothing_pushed_counts_every_commit(self):
        repo = self.repo()
        self.commit(repo, "a.txt")
        self.git(repo, "remote", "add", "origin", str(self._new_dir("remote.git")))
        self.assertEqual(gitutil.repo_state(repo), gitutil.RepoState(True, 1))


class RefsTest(GitUtilCase):
    def test_short_sha(self):
        repo = self.repo()
        self.assertIsNone(gitutil.short_sha(repo))
        self.commit(repo, "a.txt")
        sha = gitutil.short_sha(repo)
        self.assertRegex(sha, r"^[0-9a-f]{7,}$")
        self.assertEqual(self.git(repo, "rev-parse", "HEAD").strip()[:len(sha)], sha)
        self.assertIsNone(gitutil.short_sha(repo, "no-such-ref"))
        self.assertIsNone(gitutil.short_sha(repo, "--help"))
        self.assertIsNone(gitutil.short_sha(self._new_dir("plain")))

    def test_default_branch_prefers_origin_head_then_main_then_master_then_head(self):
        repo = self.repo()
        self.commit(repo, "a.txt")
        self.assertEqual(gitutil.default_branch(repo), "main")
        self.git(repo, "branch", "-m", "main", "master")
        self.assertEqual(gitutil.default_branch(repo), "master")
        self.git(repo, "branch", "-m", "master", "trunk")
        self.assertEqual(gitutil.default_branch(repo), "HEAD")
        self.git(repo, "branch", "develop")
        self.git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
        self.git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        self.assertEqual(gitutil.default_branch(repo), "develop")

    def test_default_branch_of_an_unborn_repo_is_head(self):
        self.assertEqual(gitutil.default_branch(self.repo()), "HEAD")


class ArchiveTest(GitUtilCase):
    def test_archive_returns_committed_files_with_normalised_modes(self):
        repo = self.repo()
        self.commit(repo, "a.txt", "alpha\n")
        self.commit(repo, "bin/run.sh", "#!/bin/sh\n", mode=0o755)
        self.commit(repo, "sub dir/b c.txt", "beta\n")
        (repo / "untracked.txt").write_text("u", encoding="utf-8")
        (repo / "a.txt").write_text("edited, not committed\n", encoding="utf-8")
        got = gitutil.archive(repo, "HEAD")
        self.assertEqual(
            got,
            {"a.txt": (b"alpha\n", 0o644), "bin/run.sh": (b"#!/bin/sh\n", 0o755), "sub dir/b c.txt": (b"beta\n", 0o644)},
        )

    def test_archive_reads_the_named_ref_not_the_checkout(self):
        repo = self.repo()
        self.commit(repo, "a.txt", "one\n")
        self.git(repo, "tag", "v1")
        self.commit(repo, "a.txt", "two\n")
        self.assertEqual(gitutil.archive(repo, "v1")["a.txt"][0], b"one\n")
        self.assertEqual(gitutil.archive(repo, "HEAD")["a.txt"][0], b"two\n")

    def test_archive_of_a_bad_ref_is_a_git_error(self):
        repo = self.repo()
        self.commit(repo, "a.txt")
        with self.assertRaises(gitutil.GitError):
            gitutil.archive(repo, "no-such-ref")
        with self.assertRaises(gitutil.GitError):
            gitutil.archive(repo, "--output=x")


if __name__ == "__main__":
    unittest.main()
