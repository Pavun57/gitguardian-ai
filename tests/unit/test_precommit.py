"""Unit tests for the pre-commit staged-diff scanner."""

from security.hooks.precommit_scan import scan

DIFF_WITH_KEY_MATERIAL = """diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -1,2 +1,3 @@
 debug = True
+AWS_KEY = "AKIAQ7Z9W2X5V8B1N4M6"
-old_line_removed_is_not_scanned = "AKIAZZZZZZZZZZZZZZZZ"
"""

DIFF_CLEAN = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 debug = True
+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # documented example placeholder
+password = "changeme"
"""

DIFF_NO_SECRETS = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-x = 1
+x = 2
"""


def test_detects_aws_key_in_added_line():
    hits = scan(DIFF_WITH_KEY_MATERIAL)
    assert len(hits) == 1
    assert hits[0][0] == "config.py"
    assert "AWS" in hits[0][1]


def test_removed_lines_ignored():
    # The AKIAZZZ key is on a removed (-) line — not staged content
    hits = scan(DIFF_WITH_KEY_MATERIAL)
    assert all("ZZZZ" not in h[2] for h in hits)


def test_placeholder_allowlisted():
    assert scan(DIFF_CLEAN) == []


def test_clean_diff_passes():
    assert scan(DIFF_NO_SECRETS) == []


def test_private_key_detected():
    diff = "+++ b/key.pem\n@@ -0,0 +1 @@\n+-----BEGIN RSA PRIVATE KEY-----\n"
    hits = scan(diff)
    assert any("Private key" in h[1] for h in hits)
