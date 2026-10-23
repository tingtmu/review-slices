"""Merges: a trailer covers only its own history, and a merge counts where it differs from git's own merge."""
import os
import unittest

from support import Repo, load_guard


class UnitsFollowHistoryTest(unittest.TestCase):
    def two_branches_merged(self, first, second):
        repo = Repo(self)
        repo.install()
        repo.git("switch", "-q", "-c", "a", "main")
        repo.write("src/a.py")
        repo.commit("a1", trailer=repo.trailer("simple"))
        repo.write("src/a2.py")
        repo.commit("a2, never reviewed")
        repo.git("switch", "-q", "-c", "b", "main")
        repo.write("src/b.py")
        repo.commit("b1", trailer=repo.trailer("simple"))
        repo.git("switch", "-q", first)
        repo.git("merge", "-q", "--no-ff", "--no-edit", second)
        self.assertEqual(repo.run_suite().returncode, 0)
        return repo.try_push("origin", "HEAD:refs/heads/merged")

    def test_a_trailer_on_one_branch_never_covers_the_other_with_a_first(self):  # Phase 3 review B1
        done = self.two_branches_merged("a", "b")
        self.assertNotEqual(done.returncode, 0, done.stderr)
        self.assertIn("no review trailer covers", done.stderr)

    def test_a_trailer_on_one_branch_never_covers_the_other_with_b_first(self):
        done = self.two_branches_merged("b", "a")
        self.assertNotEqual(done.returncode, 0, done.stderr)


class MergePathsTest(unittest.TestCase):
    """The fallback for git before 2.36 and octopus merges, called in-process to force it on any git."""

    def setUp(self):
        self.repo = Repo(self)
        self.guard = load_guard()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.repo.path)

    def merge(self, *branches, keep=None):
        """Merge BRANCHES into main; restore KEEP (a path) to main's version before committing."""
        repo = self.repo
        repo.git("switch", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "--no-commit", *branches)
        if keep:
            repo.git("checkout", "HEAD", "--", keep)
        repo.git("commit", "-q", "--no-edit")
        head = repo.out("rev-parse", "HEAD")
        return head, repo.out("rev-list", "--parents", "-n", "1", head).split()[1:]

    def branch(self, name, path, text="changed\n"):
        repo = self.repo
        repo.git("switch", "-q", "-c", name, "main")
        repo.write(path, text)
        repo.commit("change " + path)

    def test_a_dropped_change_is_counted(self):
        self.repo.write("core/a.py", "before\n")
        self.repo.commit("base")
        self.branch("other", "core/a.py", "after\n")
        head, parents = self.merge("other", keep="core/a.py")
        self.assertEqual(self.guard.merge_paths_by_side(head, parents), ["core/a.py"])

    def test_a_clean_merge_of_one_file_both_sides_edited_counts_nothing(self):
        self.repo.write("core/a.py", "one\n1\n2\n3\n4\ntwo\n")
        self.repo.commit("base")
        self.branch("other", "core/a.py", "one\n1\n2\n3\n4\nTWO\n")
        self.repo.git("switch", "-q", "main")
        self.repo.write("core/a.py", "ONE\n1\n2\n3\n4\ntwo\n")
        self.repo.commit("main's edit")
        head, parents = self.merge("other")
        self.assertEqual(self.guard.merge_paths_by_side(head, parents), [])

    def test_a_clean_merge_of_separate_files_counts_nothing(self):
        self.branch("other", "src/x.py")
        self.repo.git("switch", "-q", "main")
        self.repo.write("src/y.py")
        self.repo.commit("main's own change")
        head, parents = self.merge("other")
        self.assertEqual(self.guard.merge_paths_by_side(head, parents), [])

    def test_an_octopus_merge_that_drops_a_change_is_counted(self):
        self.repo.write("core/a.py", "before\n")
        self.repo.commit("base")
        self.branch("one", "core/a.py", "after\n")
        self.branch("two", "src/b.py")
        head, parents = self.merge("one", "two", keep="core/a.py")
        self.assertEqual(len(parents), 3)
        self.assertIn("core/a.py", self.guard.commit_paths(head))
        self.assertNotIn("src/b.py", self.guard.commit_paths(head))


if __name__ == "__main__":
    unittest.main()
