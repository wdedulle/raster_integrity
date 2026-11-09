"""
test_archiving.py
=================
Pytest-tests for BagItArchive.

"""

import os

import bagit
import pytest
from raster_integrity.techniques.archiving import BagItArchive

ROOT_HASH = "abc123def456"
CONTENT = b"fake geotiff content"


@pytest.fixture
def tif_file(tmp_path):
    path = tmp_path / "survey.tif"
    path.write_bytes(CONTENT)
    return str(path)


@pytest.fixture
def archive(tif_file):
    return BagItArchive(file=tif_file)


def _bag_dir(tif_file):
    root, _ = os.path.splitext(tif_file)
    return f"{root}_bagit"


def test_constructor_stores_file(tif_file):
    assert BagItArchive(file=tif_file)._file == tif_file


def test_constructor_requires_file():
    with pytest.raises(TypeError, match="file"):
        BagItArchive()


def test_constructor_rejects_nonexistent_file(tmp_path):
    missing = str(tmp_path / "missing.tif")
    with pytest.raises(ValueError, match="does not exist"):
        BagItArchive(file=missing)


def test_label(archive):
    assert archive.label() == "archive_bagit"


def test_get_directory(archive, tif_file):
    root, _ = os.path.splitext(tif_file)
    assert archive._get_directory(tif_file) == f"{root}_bagit"


def test_get_directory_strips_only_last_extension(archive, tmp_path):
    f = str(tmp_path / "survey.v2.tif")
    assert archive._get_directory(f) == str(tmp_path / "survey.v2_bagit")


def test_create_directory_creates_and_is_idempotent(archive, tif_file):
    expected = _bag_dir(tif_file)
    assert not os.path.exists(expected)

    first = archive._create_directory(tif_file)
    assert first == expected
    assert os.path.isdir(expected)

    second = archive._create_directory(tif_file)
    assert second == expected


def test_create_integrity_requires_root_hash(archive):
    with pytest.raises(TypeError, match="root_hash"):
        archive.create_integrity()


def test_create_integrity_rejects_wrong_kwargs(archive):
    with pytest.raises(TypeError, match="root_hash"):
        archive.create_integrity(something_else="x")


def test_missing_root_hash_does_not_touch_filesystem(archive, tif_file):
    with pytest.raises(TypeError):
        archive.create_integrity()
    assert not os.path.exists(_bag_dir(tif_file))


def test_create_integrity_returns_bag(archive):
    bag = archive.create_integrity(root_hash=ROOT_HASH)
    assert isinstance(bag, bagit.Bag)


def test_bag_has_required_structure(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    bag_dir = _bag_dir(tif_file)

    for name in ("bagit.txt", "bag-info.txt", "manifest-sha256.txt"):
        assert os.path.isfile(os.path.join(bag_dir, name)), name
    assert os.path.isdir(os.path.join(bag_dir, "data"))


def test_payload_is_in_data_dir(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    payload = os.path.join(_bag_dir(tif_file), "data", "survey.tif")

    assert os.path.isfile(payload)
    with open(payload, "rb") as fh:
        assert fh.read() == CONTENT


def test_fingerprint_stored_in_bag_info(archive, tif_file):
    bag = archive.create_integrity(root_hash=ROOT_HASH)
    assert bag.info["fingerprint"] == ROOT_HASH

    reopened = bagit.Bag(_bag_dir(tif_file))
    assert reopened.info["fingerprint"] == ROOT_HASH


def test_bag_validates(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    bag = bagit.Bag(_bag_dir(tif_file))
    assert bag.validate() is True


def test_manifest_lists_payload(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    manifest = os.path.join(_bag_dir(tif_file), "manifest-sha256.txt")
    with open(manifest, encoding="utf-8") as fh:
        assert "data/survey.tif" in fh.read()


def test_original_file_is_untouched(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    assert os.path.isfile(tif_file)
    with open(tif_file, "rb") as fh:
        assert fh.read() == CONTENT


def test_aux_xml_is_copied_into_bag(archive, tif_file):
    aux_content = b"<PAMDataset/>"
    with open(f"{tif_file}.aux.xml", "wb") as fh:
        fh.write(aux_content)

    archive.create_integrity(root_hash=ROOT_HASH)

    data_dir = os.path.join(_bag_dir(tif_file), "data")
    aux_in_bag = os.path.join(data_dir, "survey.tif.aux.xml")
    assert os.path.isfile(aux_in_bag)
    with open(aux_in_bag, "rb") as fh:
        assert fh.read() == aux_content

    manifest = os.path.join(_bag_dir(tif_file), "manifest-sha256.txt")
    with open(manifest, encoding="utf-8") as fh:
        assert "data/survey.tif.aux.xml" in fh.read()


def test_no_aux_xml_is_fine(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    data_dir = os.path.join(_bag_dir(tif_file), "data")
    assert os.listdir(data_dir) == ["survey.tif"]


def test_existing_directory_is_replaced(archive, tif_file):
    bag_dir = _bag_dir(tif_file)
    os.makedirs(bag_dir)
    stale = os.path.join(bag_dir, "stale.txt")
    with open(stale, "w") as fh:
        fh.write("oud")

    archive.create_integrity(root_hash=ROOT_HASH)

    assert not os.path.exists(stale)
    assert bagit.Bag(bag_dir).validate() is True


def test_can_run_twice_with_new_hash(archive, tif_file):
    archive.create_integrity(root_hash="first")
    bag = archive.create_integrity(root_hash="second")

    assert bag.info["fingerprint"] == "second"
    assert bag.validate() is True


def test_root_hash_is_stored_on_instance(archive):
    archive.create_integrity(root_hash=ROOT_HASH)
    assert archive._root_hash == ROOT_HASH


def test_modified_payload_fails_validation(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    payload = os.path.join(_bag_dir(tif_file), "data", "survey.tif")

    with open(payload, "ab") as fh:
        fh.write(b"bit rot")

    with pytest.raises(bagit.BagValidationError):
        bagit.Bag(_bag_dir(tif_file)).validate()


def test_deleted_payload_fails_validation(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    os.remove(os.path.join(_bag_dir(tif_file), "data", "survey.tif"))

    with pytest.raises(bagit.BagValidationError):
        bagit.Bag(_bag_dir(tif_file)).validate()


def test_extra_payload_file_fails_validation(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    extra = os.path.join(_bag_dir(tif_file), "data", "extra.tif")
    with open(extra, "wb") as fh:
        fh.write(b"onverwacht")

    with pytest.raises(bagit.BagValidationError):
        bagit.Bag(_bag_dir(tif_file)).validate()


def test_modified_fingerprint_fails_tag_validation(archive, tif_file):
    archive.create_integrity(root_hash=ROOT_HASH)
    info = os.path.join(_bag_dir(tif_file), "bag-info.txt")

    with open(info, encoding="utf-8") as fh:
        text = fh.read()
    with open(info, "w", encoding="utf-8") as fh:
        fh.write(text.replace(ROOT_HASH, "tampered"))

    with pytest.raises(bagit.BagValidationError):
        bagit.Bag(_bag_dir(tif_file)).validate()
