"""A host may load only the start of SKILL.md. Codex injects at most 8,000 bytes of a mentioned skill, silently; Claude
Code re-attaches at most 5,000 tokens of a skill after compaction. A host that cuts it sees the guard sentence near
the top, which asks for a full read when the end marker is missing. That sentence, the marker and the Report are the
hard rules here; the size is a soft ceiling, which warns and never fails: exceed it with a reason.

Measured 2026-10-30 with `claude -p` usage deltas (Haiku and Opus agreed): the 13,562-byte SKILL.md was 4,672 tokens,
about 2.9 bytes a token, so 14,000 bytes is about 4,820 tokens, under Claude Code's 5,000 with a margin."""
import os
import re
import unittest
import warnings

from support import ROOT, SCRIPTS, read_text

SKILL_DIR = os.path.join(ROOT, "skills", "review-slices")
SKILL = os.path.join(SKILL_DIR, "SKILL.md")
REFERENCES = os.path.join(SKILL_DIR, "references")
SOFT_MAX_BYTES = 14000
GUARD_BEFORE = 1000
MARKER = "End of review-slices SKILL.md."
MOVED = {"A secret turns up": "secrets.md", "Record an incident": "incidents.md", "Set up a repo": "set-up.md"}
LINK = re.compile(r"\]\(([^)\s]+)\)")


def slug(heading):
    """A markdown heading's anchor, as GitHub makes it."""
    return re.sub(r"[^\w\- ]", "", heading.lstrip("#").strip().lower()).replace(" ", "-")


def warn_if_over(size):
    if size > SOFT_MAX_BYTES:
        warnings.warn("SKILL.md is %d bytes, over the soft ceiling of %d: past about 14,500 Claude Code's re-attach "
                      "cuts the end; move text to references/ if you can" % (size, SOFT_MAX_BYTES))


def skill_bytes():
    with open(SKILL, "rb") as handle:
        return handle.read()


class SkillSizeTest(unittest.TestCase):
    def test_the_size_never_fails_and_warns_only_over_the_soft_ceiling(self):
        warn_if_over(len(skill_bytes()))
        with self.assertWarnsRegex(UserWarning, "soft ceiling"):
            warn_if_over(SOFT_MAX_BYTES + 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warn_if_over(SOFT_MAX_BYTES)

    def test_report_is_in_skill_md(self):
        self.assertIn(b"\n## Report\n", skill_bytes())

    def test_the_marker_ends_the_file_and_the_guard_sentence_names_it_near_the_top(self):
        text = skill_bytes()
        self.assertTrue(text.endswith(b"\n\n" + MARKER.encode() + b"\n"), text[-80:])
        guard = text.find(b"read the whole file before acting.")
        self.assertNotEqual(guard, -1)
        self.assertLess(guard, GUARD_BEFORE)
        self.assertIn(("`%s`" % MARKER).encode(), text[:guard])

    def test_every_relative_link_resolves(self):
        """Templates are left out: their links are relative to the adopting repo."""
        paths = [SKILL, os.path.join(SKILL_DIR, "GLOSSARY.md"), os.path.join(ROOT, "README.md")] + [
            os.path.join(REFERENCES, name) for name in sorted(os.listdir(REFERENCES))]
        for path in paths:
            for target in LINK.findall(read_text(path)):
                if re.match(r"[a-z]+:", target):
                    continue
                where = "%s: %s" % (os.path.relpath(path, ROOT), target)
                self.assertFalse(target.startswith("#"), where + ", an anchor that a move would break")
                name, _, fragment = target.partition("#")
                resolved = os.path.join(os.path.dirname(path), name)
                self.assertTrue(os.path.exists(resolved), where)
                if fragment:
                    self.assertIn(fragment, [slug(line) for line in read_text(resolved).splitlines()
                                             if line.startswith("#")], where)

    def test_the_guard_s_messages_name_a_heading_that_exists(self):
        named = set()
        for script in ("review_slices.py", "secret_scan.py"):
            named.update(re.findall(r"the skill's \\\"([^\\]+)\\\"", read_text(os.path.join(SCRIPTS, script))))
        self.assertEqual(named, {"A secret turns up", "Set up a repo"})
        skill = read_text(SKILL)
        for title, name in MOVED.items():
            self.assertTrue(read_text(os.path.join(REFERENCES, name)).startswith("# %s\n" % title), name)
            self.assertIn("[%s](references/%s)" % (title, name), skill)


if __name__ == "__main__":
    unittest.main()
