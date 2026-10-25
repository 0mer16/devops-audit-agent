from redact import redact


def test_known_tokens_masked():
    text = "key = AKIAABCDEFGHIJKLMNOP and ghp_" + "a" * 36
    out = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in out and "ghp_aaaa" not in out


def test_quoted_secret_masked_but_name_kept():
    out = redact('DB_PASSWORD = "SuperSecret123!"')
    assert "SuperSecret123!" not in out
    assert "DB_PASSWORD" in out


def test_env_style_masked():
    out = redact("SECRET_KEY=s3cr3tvalue99\n")
    assert "s3cr3tvalue99" not in out


def test_placeholders_and_references_left_alone():
    for line in ['API_KEY = "your-api-key-here"', "password: ${{ secrets.DB_PASS }}",
                 'token = os.getenv("TOKEN")']:
        assert redact(line) == line
