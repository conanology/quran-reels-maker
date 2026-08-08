"""
Tests thumbnail MIME detection.

The type was hardcoded to image/jpeg, while documentary/ writes thumbnail.png,
so those uploads declared the wrong format.
"""
from pathlib import Path

import pytest

from youtube.uploader import thumbnail_mimetype


class TestThumbnailMimetype:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("thumb.jpg", "image/jpeg"),
            ("thumb.jpeg", "image/jpeg"),
            ("thumb.JPG", "image/jpeg"),
            ("thumb.png", "image/png"),
            ("thumb.PNG", "image/png"),
        ],
    )
    def test_supported_formats(self, name, expected):
        assert thumbnail_mimetype(Path(name)) == expected

    @pytest.mark.parametrize("name", ["thumb.webp", "thumb.gif", "thumb", "a.bmp"])
    def test_unsupported_formats_return_none(self, name):
        """YouTube's thumbnails.set accepts JPEG and PNG only"""
        assert thumbnail_mimetype(Path(name)) is None
