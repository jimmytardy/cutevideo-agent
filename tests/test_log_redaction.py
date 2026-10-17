from __future__ import annotations

import logging

import httpx
import pytest

from agent.core.log_redaction import REDACTED, RedactSecretsFilter, redact_url, setup_logging


@pytest.mark.parametrize("url, expected", [
    ("https://graph.facebook.com/v19.0/me?access_token=EAAG123", f"https://graph.facebook.com/v19.0/me?access_token={REDACTED}"),
    ("/api/v1/projects/1/studio/file?path=voice.wav&access_token=eyJ.a.b",
     f"/api/v1/projects/1/studio/file?path=voice.wav&access_token={REDACTED}"),
    ("https://x.googleapis.com/v1/m?key=AIzaXYZ&alt=json", f"https://x.googleapis.com/v1/m?key={REDACTED}&alt=json"),
    ("https://b.s3.amazonaws.com/v.mp4?X-Amz-Credential=AK%2F1&X-Amz-Signature=abc",
     f"https://b.s3.amazonaws.com/v.mp4?X-Amz-Credential={REDACTED}&X-Amz-Signature={REDACTED}"),
    # Paramètres non sensibles intacts ; `monkey=` ne doit pas être pris pour `key=`.
    ("/api/v1/projects?page=2&monkey=1", "/api/v1/projects?page=2&monkey=1"),
])
def test_redact_url(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_filter_redacts_httpx_url_args_and_uvicorn_access_line() -> None:
    f = RedactSecretsFilter()
    httpx_record = logging.LogRecord("httpx", logging.INFO, __file__, 1, 'HTTP Request: %s %s "%s %d %s"',
                                     ("GET", httpx.URL("https://graph.facebook.com/me?access_token=SECRET"),
                                      "HTTP/1.1", 200, "OK"), None)
    access_record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                      ("1.2.3.4:5", "GET", "/api/v1/x?access_token=JWT", "1.1", 200), None)
    for record in (httpx_record, access_record):
        assert f.filter(record)
        message = record.getMessage()
        assert "SECRET" not in message and "JWT" not in message and REDACTED in message
    assert access_record.args[-1] == 200  # arguments non textuels inchangés (%d)


def test_setup_logging_installs_the_filter_once() -> None:
    setup_logging()
    setup_logging()
    for name in ("httpx", "uvicorn.access"):
        assert sum(isinstance(f, RedactSecretsFilter) for f in logging.getLogger(name).filters) == 1
