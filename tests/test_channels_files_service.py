"""Tests for channels_files_service — companion detection, audit helpers."""

from py_captions_for_channels.services.channels_files_service import (
    _cancelled_result,
    _extract_title,
    _is_companion_of_api_file,
    audit_files,
)


class TestIsCompanionOfApiFile:
    def test_srt_companion(self):
        api_files = {"show.mpg"}
        assert _is_companion_of_api_file("show.mpg.srt", api_files) is True

    def test_orig_companion(self):
        api_files = {"show.mpg"}
        assert _is_companion_of_api_file("show.mpg.orig", api_files) is True

    def test_cc4chan_temp(self):
        api_files = {"show.mpg"}
        assert _is_companion_of_api_file("show.mpg.cc4chan.orig", api_files) is True

    def test_cc4chan_muxed(self):
        api_files = {"show.mpg"}
        assert (
            _is_companion_of_api_file("show.mpg.cc4chan.muxed.mp4", api_files) is True
        )

    def test_unrelated_file(self):
        api_files = {"show.mpg"}
        assert _is_companion_of_api_file("other.txt", api_files) is False

    def test_srt_without_extension(self):
        # "show.srt" where "show.mpg" is in API — base "show" matches "show.mpg"
        api_files = {"show.mpg"}
        assert _is_companion_of_api_file("show.srt", api_files) is True

    def test_empty_api_set(self):
        assert _is_companion_of_api_file("show.mpg.srt", set()) is False


class TestExtractTitle:
    def test_with_airing_title(self):
        rec = {"Airing": {"Title": "Morning News"}}
        assert _extract_title(rec) == "Morning News"

    def test_fallback_to_path(self):
        rec = {"Airing": {}, "Path": "TV/show/episode.mpg"}
        assert _extract_title(rec) == "episode"

    def test_fallback_to_id(self):
        rec = {"Airing": {}, "ID": 42}
        assert _extract_title(rec) == "ID 42"


class TestCancelledResult:
    def test_structure(self):
        result = _cancelled_result(10, 100)
        assert result["success"] is True
        assert result["cancelled"] is True
        assert result["summary"]["cancelled_at"] == "10/100"
        assert result["missing_files"] == []
        assert result["orphaned_files"] == []


class TestAuditFiles:
    def test_empty_api_list(self, tmp_path):
        result = audit_files([], str(tmp_path))
        assert result["success"] is True
        assert result["summary"]["api_file_count"] == 0

    def test_missing_file_detected(self, tmp_path):
        dvr_files = [{"Path": "TV/Show/ep.mpg", "ID": 1}]
        result = audit_files(dvr_files, str(tmp_path))
        assert result["summary"]["missing_count"] == 1

    def test_existing_file_not_missing(self, tmp_path):
        # Create the file on disk
        show_dir = tmp_path / "TV" / "Show"
        show_dir.mkdir(parents=True)
        (show_dir / "ep.mpg").write_bytes(b"\x00")

        dvr_files = [{"Path": "TV/Show/ep.mpg", "ID": 1}]
        result = audit_files(dvr_files, str(tmp_path))
        assert result["summary"]["missing_count"] == 0

    def test_orphaned_file_detected(self, tmp_path):
        show_dir = tmp_path / "TV" / "Show"
        show_dir.mkdir(parents=True)
        (show_dir / "ep.mpg").write_bytes(b"\x00")
        (show_dir / "random.txt").write_bytes(b"orphan")

        dvr_files = [{"Path": "TV/Show/ep.mpg", "ID": 1}]
        result = audit_files(dvr_files, str(tmp_path))
        assert result["summary"]["orphaned_count"] == 1
        assert result["orphaned_files"][0]["filename"] == "random.txt"

    def test_companion_not_orphaned(self, tmp_path):
        show_dir = tmp_path / "TV" / "Show"
        show_dir.mkdir(parents=True)
        (show_dir / "ep.mpg").write_bytes(b"\x00")
        (show_dir / "ep.mpg.srt").write_bytes(b"subs")

        dvr_files = [{"Path": "TV/Show/ep.mpg", "ID": 1}]
        result = audit_files(dvr_files, str(tmp_path))
        assert result["summary"]["orphaned_count"] == 0

    def test_cancel_check(self, tmp_path):
        show_dir = tmp_path / "TV" / "Show"
        show_dir.mkdir(parents=True)
        (show_dir / "ep.mpg").write_bytes(b"\x00")

        dvr_files = [{"Path": "TV/Show/ep.mpg", "ID": i} for i in range(10)]
        result = audit_files(
            dvr_files,
            str(tmp_path),
            cancel_check=lambda: True,
        )
        assert result["cancelled"] is True

    def test_deleted_files_flagged_as_trash(self, tmp_path):
        show_dir = tmp_path / "TV" / "Show"
        show_dir.mkdir(parents=True)
        (show_dir / "ep.mpg").write_bytes(b"\x00")
        (show_dir / "deleted.mpg").write_bytes(b"trash")

        dvr_files = [{"Path": "TV/Show/ep.mpg", "ID": 1}]
        deleted_files = [{"Path": "TV/Show/deleted.mpg", "ID": 2}]
        result = audit_files(dvr_files, str(tmp_path), deleted_files=deleted_files)
        trashed = [f for f in result["orphaned_files"] if f.get("trash")]
        assert len(trashed) == 1
