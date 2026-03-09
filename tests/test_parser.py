import pytest
from py_captions_for_channels.config import normalize_host_path


@pytest.mark.parametrize(
    "raw, expected",
    [
        # UNC — all slash/backslash variants should produce //server/share
        ("//server/share", "//server/share"),
        ("\\\\server\\share", "//server/share"),
        ("////server//share", "//server/share"),
        ("\\\\\\\\server\\\\share", "//server/share"),
        # Drive letters — backslashes become forward slashes, letter untouched
        ("Z:/", "Z:"),
        ("Z:\\", "Z:"),
        ("Z:/path/to/dir", "Z:/path/to/dir"),
        ("Z:\\path\\to\\dir", "Z:/path/to/dir"),
        # Unix absolute paths — single leading slash, left unchanged
        ("/tank/AllMedia/Channels", "/tank/AllMedia/Channels"),
        # Empty / None passthrough
        ("", ""),
    ],
)
def test_normalize_host_path(raw, expected):
    assert normalize_host_path(raw) == expected


def test_placeholder():
    assert True
