from reposentry.observability.redact import scrub_text


def test_modern_provider_tokens_are_redacted():
    values = [
        "".join(["gh", "p_", "A" * 36]),
        "".join(["gh", "o_", "B" * 36]),
        "".join(["github_", "pat_", "C" * 30]),
        "".join(["xo", "xb-", "1234567890-", "abcdefghijklmnop"]),
        "".join(["xo", "xp-", "1234567890-", "abcdefghijklmnop"]),
        "".join(["AI", "za", "D" * 35]),
    ]
    scrubbed = scrub_text(" ".join(values))
    assert all(value not in scrubbed for value in values)
    assert scrubbed.count("[REDACTED]") == len(values)


def test_private_key_block_and_database_uri_are_redacted():
    key = "".join(["-----", "BEGIN PRIVATE KEY-----\nMIIEvFakePrivateKeyMaterial\n-----", "END PRIVATE KEY-----"])
    uri = "".join(["post", "gres://alice:s3cr3t@db.example.test:5432/app"])
    scrubbed = scrub_text(f"{key} {uri}")
    assert "MIIEvFakePrivateKeyMaterial" not in scrubbed
    assert "alice:s3cr3t" not in scrubbed
    assert scrubbed.count("[REDACTED]") == 2
