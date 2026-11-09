"""
test_timestamping.py
====================
Pytest-tests for Timestamping.

"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import raster_integrity.techniques.timestamping as ts_module
from raster_integrity.techniques.timestamping import (
    CACERT_URL,
    TSA_EINDPUNTEN,
    Timestamping,
)

CONTENT = b"fake bathymetric dataset"
TSR_BYTES = b"timestamp-response-bytes"


@pytest.fixture
def data_file(tmp_path):
    path = tmp_path / "dataset.tif"
    path.write_bytes(CONTENT)
    return path


@pytest.fixture
def stamper(data_file):
    return Timestamping(file=data_file)


@pytest.fixture
def fake_tsa(monkeypatch):
    response = MagicMock(name="http_response")
    response.content = b"raw-http-body"

    decoded = MagicMock(name="timestamp_response")
    decoded.as_bytes.return_value = TSR_BYTES

    post = MagicMock(name="requests.post", return_value=response)
    decode = MagicMock(name="decode_timestamp_response", return_value=decoded)

    monkeypatch.setattr(ts_module.requests, "post", post)
    monkeypatch.setattr(ts_module, "decode_timestamp_response", decode)
    return SimpleNamespace(post=post, decode=decode, response=response, decoded=decoded)


def _urlopen_returning(content):
    resp = MagicMock(name="urlopen_response")
    resp.__enter__.return_value = resp
    resp.read.return_value = content
    return MagicMock(name="urlopen", return_value=resp)


def test_tsa_endpoints_contain_freetsa():
    assert TSA_EINDPUNTEN["freetsa"] == "https://freetsa.org/tsr"


def test_all_tsa_endpoints_are_urls():
    assert TSA_EINDPUNTEN
    for url in TSA_EINDPUNTEN.values():
        assert url.startswith(("http://", "https://"))


def test_cacert_url():
    assert CACERT_URL == "https://freetsa.org/files/cacert.pem"


def test_constructor_requires_file():
    with pytest.raises(TypeError, match="file"):
        Timestamping()


def test_constructor_accepts_str_path(data_file):
    stamper = Timestamping(file=str(data_file))
    assert stamper._file == data_file


def test_constructor_accepts_pathlib_path(data_file):
    stamper = Timestamping(file=data_file)
    assert stamper._file == data_file


def test_constructor_stores_path_object(data_file):
    assert isinstance(Timestamping(file=str(data_file))._file, Path)


def test_constructor_rejects_nonexistent_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        Timestamping(file=tmp_path / "missing.tif")


def test_constructor_rejects_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        Timestamping(file=tmp_path)


def test_label(stamper):
    assert stamper.label() == "timestamping"


def test_create_integrity_requires_tsr_name(stamper, fake_tsa):
    with pytest.raises(TypeError, match="tsr_name"):
        stamper.create_integrity()


def test_missing_tsr_name_does_not_call_network(stamper, fake_tsa):
    with pytest.raises(TypeError):
        stamper.create_integrity()
    fake_tsa.post.assert_not_called()


def test_wrong_kwarg_is_rejected(stamper, fake_tsa):
    with pytest.raises(TypeError, match="tsr_name"):
        stamper.create_integrity(name="x")


def test_returns_tsr_path(stamper, fake_tsa, tmp_path):
    tsr_name = str(tmp_path / "survey")
    assert stamper.create_integrity(tsr_name=tsr_name) == f"{tsr_name}.tsr"


def test_writes_tsr_file_with_decoded_response_bytes(stamper, fake_tsa, tmp_path):
    tsr_name = str(tmp_path / "survey")
    result = stamper.create_integrity(tsr_name=tsr_name)

    assert Path(result).is_file()
    assert Path(result).read_bytes() == TSR_BYTES


def test_writes_tsq_file_with_request_bytes(stamper, fake_tsa, tmp_path):
    tsr_name = str(tmp_path / "survey")
    stamper.create_integrity(tsr_name=tsr_name)

    tsq = Path(f"{tsr_name}.tsq")
    assert tsq.is_file()
    assert len(tsq.read_bytes()) > 0


def test_posted_data_equals_saved_tsq(stamper, fake_tsa, tmp_path):
    tsr_name = str(tmp_path / "survey")
    stamper.create_integrity(tsr_name=tsr_name)

    posted = fake_tsa.post.call_args.kwargs["data"]
    assert posted == Path(f"{tsr_name}.tsq").read_bytes()


def test_posts_to_freetsa_with_timestamp_query_header(stamper, fake_tsa, tmp_path):
    stamper.create_integrity(tsr_name=str(tmp_path / "survey"))

    fake_tsa.post.assert_called_once()
    args, kwargs = fake_tsa.post.call_args
    assert args[0] == TSA_EINDPUNTEN["freetsa"]
    assert kwargs["headers"] == {"Content-Type": "application/timestamp-query"}


def test_response_content_is_decoded(stamper, fake_tsa, tmp_path):
    stamper.create_integrity(tsr_name=str(tmp_path / "survey"))
    fake_tsa.decode.assert_called_once_with(fake_tsa.response.content)


def test_request_is_built_from_file_content(stamper, fake_tsa, monkeypatch, tmp_path):
    request = MagicMock(name="request")
    request.as_bytes.return_value = b"tsq-bytes"

    builder_cls = MagicMock(name="TimestampRequestBuilder")
    chain = builder_cls.return_value
    chain.data.return_value.nonce.return_value.build.return_value = request
    monkeypatch.setattr(ts_module, "TimestampRequestBuilder", builder_cls)

    tsr_name = str(tmp_path / "survey")
    stamper.create_integrity(tsr_name=tsr_name)

    chain.data.assert_called_once_with(CONTENT)
    chain.data.return_value.nonce.assert_called_once_with()
    assert Path(f"{tsr_name}.tsq").read_bytes() == b"tsq-bytes"
    assert fake_tsa.post.call_args.kwargs["data"] == b"tsq-bytes"


def test_different_files_give_different_requests(tmp_path, fake_tsa):
    a = tmp_path / "a.tif"
    b = tmp_path / "b.tif"
    a.write_bytes(b"content A")
    b.write_bytes(b"content B")

    Timestamping(file=a).create_integrity(tsr_name=str(tmp_path / "a"))
    Timestamping(file=b).create_integrity(tsr_name=str(tmp_path / "b"))

    assert (tmp_path / "a.tsq").read_bytes() != (tmp_path / "b.tsq").read_bytes()


def test_source_file_is_not_modified(stamper, fake_tsa, data_file, tmp_path):
    stamper.create_integrity(tsr_name=str(tmp_path / "survey"))
    assert data_file.read_bytes() == CONTENT


def test_existing_tsr_is_overwritten(stamper, fake_tsa, tmp_path):
    tsr_name = str(tmp_path / "survey")
    Path(f"{tsr_name}.tsr").write_bytes(b"old")

    stamper.create_integrity(tsr_name=tsr_name)

    assert Path(f"{tsr_name}.tsr").read_bytes() == TSR_BYTES


def test_can_be_called_twice(stamper, fake_tsa, tmp_path):
    tsr_name = str(tmp_path / "survey")
    stamper.create_integrity(tsr_name=tsr_name)
    stamper.create_integrity(tsr_name=tsr_name)
    assert fake_tsa.post.call_count == 2


def test_network_error_propagates_and_no_tsr_is_written(stamper, fake_tsa, tmp_path):
    fake_tsa.post.side_effect = requests.ConnectionError("TSA unreachable")
    tsr_name = str(tmp_path / "survey")

    with pytest.raises(requests.ConnectionError):
        stamper.create_integrity(tsr_name=tsr_name)

    assert not Path(f"{tsr_name}.tsr").exists()


def test_timeout_propagates(stamper, fake_tsa, tmp_path):
    fake_tsa.post.side_effect = requests.Timeout("too slow")
    with pytest.raises(requests.Timeout):
        stamper.create_integrity(tsr_name=str(tmp_path / "survey"))


def test_undecodable_response_propagates_and_no_tsr_is_written(
    stamper, fake_tsa, tmp_path
):
    fake_tsa.decode.side_effect = ValueError("invalid TimeStampResp")
    tsr_name = str(tmp_path / "survey")

    with pytest.raises(ValueError):
        stamper.create_integrity(tsr_name=tsr_name)

    assert not Path(f"{tsr_name}.tsr").exists()


def test_file_removed_after_construction_raises(stamper, fake_tsa, data_file, tmp_path):
    data_file.unlink()
    with pytest.raises(FileNotFoundError):
        stamper.create_integrity(tsr_name=str(tmp_path / "survey"))
    fake_tsa.post.assert_not_called()


def test_unwritable_output_location_raises(stamper, fake_tsa, tmp_path):
    missing_dir = tmp_path / "does_not_exist" / "survey"
    with pytest.raises(FileNotFoundError):
        stamper.create_integrity(tsr_name=str(missing_dir))


def test_ensure_file_existing_file_is_not_downloaded(stamper, monkeypatch, tmp_path):
    existing = tmp_path / "cacert.pem"
    existing.write_bytes(b"already here")
    urlopen = _urlopen_returning(b"new content")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    result = stamper._ensure_file(str(existing))

    assert result == str(existing)
    urlopen.assert_not_called()
    assert existing.read_bytes() == b"already here"


def test_ensure_file_downloads_missing_file(stamper, monkeypatch, tmp_path):
    target = tmp_path / "cacert.pem"
    urlopen = _urlopen_returning(b"PEM DATA")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    result = stamper._ensure_file(str(target))

    assert result == str(target)
    assert target.read_bytes() == b"PEM DATA"


def test_ensure_file_uses_default_url_and_timeout(stamper, monkeypatch, tmp_path):
    urlopen = _urlopen_returning(b"x")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    stamper._ensure_file(str(tmp_path / "cacert.pem"))

    urlopen.assert_called_once_with(CACERT_URL, timeout=30)


def test_ensure_file_uses_custom_url(stamper, monkeypatch, tmp_path):
    urlopen = _urlopen_returning(b"x")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    stamper._ensure_file(str(tmp_path / "other.pem"), url="https://example.org/ca.pem")

    urlopen.assert_called_once_with("https://example.org/ca.pem", timeout=30)


def test_ensure_file_creates_parent_directories(stamper, monkeypatch, tmp_path):
    target = tmp_path / "data" / "tsa_cert" / "cacert.pem"
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(b"PEM"))

    stamper._ensure_file(str(target))

    assert target.read_bytes() == b"PEM"


def test_ensure_file_works_with_relative_path_without_directory(
    stamper, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(b"PEM"))

    stamper._ensure_file("cacert.pem")

    assert (tmp_path / "cacert.pem").read_bytes() == b"PEM"


def test_ensure_file_leaves_no_part_file_after_success(stamper, monkeypatch, tmp_path):
    target = tmp_path / "cacert.pem"
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(b"PEM"))

    stamper._ensure_file(str(target))

    assert not Path(f"{target}.part").exists()


def test_ensure_file_download_failure_propagates_and_leaves_nothing(
    stamper, monkeypatch, tmp_path
):
    target = tmp_path / "cacert.pem"
    monkeypatch.setattr(
        "urllib.request.urlopen", MagicMock(side_effect=OSError("netwerk down"))
    )

    with pytest.raises(OSError, match="netwerk down"):
        stamper._ensure_file(str(target))

    assert not target.exists()
    assert not Path(f"{target}.part").exists()


def test_ensure_file_failure_during_read_cleans_up_part_file(
    stamper, monkeypatch, tmp_path
):
    target = tmp_path / "cacert.pem"
    urlopen = _urlopen_returning(b"")
    urlopen.return_value.read.side_effect = ConnectionResetError("verbroken")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(ConnectionResetError):
        stamper._ensure_file(str(target))

    assert not target.exists(), "nooit een half bestand onder de echte naam"
    assert not Path(f"{target}.part").exists()


def test_ensure_file_failure_does_not_touch_existing_target_semantics(
    stamper, monkeypatch, tmp_path
):
    target = tmp_path / "cacert.pem"
    Path(f"{target}.part").write_bytes(b"stale partial")
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_returning(b"fresh"))

    stamper._ensure_file(str(target))

    assert target.read_bytes() == b"fresh"
    assert not Path(f"{target}.part").exists()
