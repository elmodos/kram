"""Parsing what rpmkeys and rpm -V print about a package file and an installed package."""
import pytest

pytest.importorskip("rpm")

from kram.core import local_rpm
from kram.core.local_rpm import parse_verify


def test_signature_states(monkeypatch):
    monkeypatch.setattr(local_rpm, "_signer", lambda key: "Fedora (44) <fedora-44-primary@fedoraproject.org>")
    ok = local_rpm._signature("""/tmp/hello.rpm:
    Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: 36f612dcf27f7d1a48a835e4dbfcf71c6d9f90a6: OK
    Header SHA256 digest: OK
    Payload SHA256 digest: OK
""")
    assert (ok.state, ok.key, ok.signer) == ("ok", "36f612dcf27f7d1a48a835e4dbfcf71c6d9f90a6",
                                             "Fedora (44) <fedora-44-primary@fedoraproject.org>")
    old_rpm = local_rpm._signature("    Header V4 RSA/SHA256 Signature, key ID 6d9f90a6: OK\n")
    assert (old_rpm.state, old_rpm.key) == ("ok", "6d9f90a6")
    nokey = local_rpm._signature("    Header OpenPGP V4 RSA/SHA256 signature, key ID dbfcf71c6d9f90a6: NOKEY\n")
    assert (nokey.state, nokey.key) == ("nokey", "dbfcf71c6d9f90a6")
    assert local_rpm._signature("    Header SHA256 digest: OK\n    Payload SHA256 digest: OK\n").state == "unsigned"
    bad = local_rpm._signature("""    Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: 36f6: OK
    Payload SHA3-256 digest: NOTFOUND
    Payload SHA256 digest: BAD (Expected 551f != 1623)
""")
    assert bad.state == "bad"


def test_parse_verify():
    v = parse_verify("""missing     /usr/bin/hello
S.5....T.  c /etc/hello.conf
.M.......    /usr/share/licenses/hello
missing   l /usr/share/licenses/hello/COPYING (Permission denied)
..?......    /usr/lib/secret
""")
    assert v.missing == ["/usr/bin/hello"]
    assert v.changed == [("/etc/hello.conf", "S.5....T.", True), ("/usr/share/licenses/hello", ".M.......", False)]
    assert v.unreadable == ["/usr/share/licenses/hello/COPYING", "/usr/lib/secret"]
    assert v.problems == 3
    assert parse_verify("").problems == 0
