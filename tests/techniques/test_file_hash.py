"""
test_file_hash.py
=================
Pytest-tests for FileHash.

"""

import hashlib
import os

import pytest

from raster_integrity.techniques.file_hash import FileHash

CHUNK = 65536  # 64 KB, such as the implementation


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


@pytest.fixture
def small_file(tmp_path):
    return _write(tmp_path, "small.tif", b"hello bathymetry")


@pytest.fixture
def hasher(small_file):
    return FileHash(file=small_file)


def test_label(hasher):
    assert hasher.label() == "file_hash"


def test_constructor_requires_file():
    with pytest.raises(TypeError, match="file"):
        FileHash()


def test_constructor_rejects_nonexistent_file(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        FileHash(file=str(tmp_path / "missing.tif"))


def test_default_algorithm_is_sha256(hasher, small_file):
    with open(small_file, "rb") as fh:
        expected = hashlib.sha256(fh.read()).hexdigest()
    assert hasher.create_integrity() == expected


def test_default_algorithm_is_stored_on_instance(hasher):
    hasher.create_integrity()
    assert hasher._algorithm == "sha256"


def test_known_sha256_vector(tmp_path):
    # SHA-256("abc") FROM NIST FIPS 180-4
    path = _write(tmp_path, "abc.bin", b"abc")
    digest = FileHash(file=path).create_integrity()
    assert digest == (
        "ba7816bf8f01cfea414140de5dae2223" "b00361a396177a9cb410ff61f20015ad"
    )


def test_digest_is_lowercase_hex_of_expected_length(hasher):
    digest = hasher.create_integrity()
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


@pytest.mark.parametrize(
    "algorithm",
    ["sha1", "sha224", "sha256", "sha384", "sha512", "md5", "sha3_256", "blake2b"],
)
def test_supported_algorithms_match_hashlib(tmp_path, algorithm):
    content = b"survey data " * 1000
    path = _write(tmp_path, "data.tif", content)

    digest = FileHash(file=path).create_integrity(algorithm=algorithm)

    assert digest == hashlib.new(algorithm, content).hexdigest()


def test_explicit_algorithm_is_stored_on_instance(hasher):
    hasher.create_integrity(algorithm="sha512")
    assert hasher._algorithm == "sha512"


def test_different_algorithms_give_different_digests(hasher):
    assert hasher.create_integrity(algorithm="sha256") != hasher.create_integrity(
        algorithm="sha512"
    )


def test_algorithm_resets_to_default_on_next_call(hasher):
    sha512 = hasher.create_integrity(algorithm="sha512")
    default = hasher.create_integrity()

    assert hasher._algorithm == "sha256"
    assert len(sha512) == 128
    assert len(default) == 64


def test_unknown_algorithm_raises_value_error(hasher):
    with pytest.raises(ValueError):
        hasher.create_integrity(algorithm="not-a-real-algorithm")


def test_unrelated_kwargs_are_ignored(hasher, small_file):
    with open(small_file, "rb") as fh:
        expected = hashlib.sha256(fh.read()).hexdigest()
    assert hasher.create_integrity(foo="bar") == expected


@pytest.mark.parametrize(
    "size",
    [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 2 * CHUNK, 3 * CHUNK + 123, 1_000_000],
)
def test_chunk_boundaries_match_hashlib(tmp_path, size):
    content = os.urandom(size)
    path = _write(tmp_path, f"file_{size}.bin", content)

    digest = FileHash(file=path).create_integrity()

    assert digest == hashlib.sha256(content).hexdigest()


def test_empty_file_gives_empty_digest(tmp_path):
    path = _write(tmp_path, "empty.tif", b"")
    digest = FileHash(file=path).create_integrity()
    assert digest == hashlib.sha256(b"").hexdigest()
    assert digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_digest_is_deterministic(hasher):
    assert hasher.create_integrity() == hasher.create_integrity()


def test_single_byte_change_changes_digest(tmp_path):
    original = b"A" * 100_000
    modified = bytearray(original)
    modified[50_000] ^= 0x01

    d1 = FileHash(file=_write(tmp_path, "a.tif", original)).create_integrity()
    d2 = FileHash(file=_write(tmp_path, "b.tif", bytes(modified))).create_integrity()

    assert d1 != d2


def test_change_in_last_chunk_is_detected(tmp_path):
    original = os.urandom(CHUNK * 2 + 10)
    modified = original[:-1] + bytes([original[-1] ^ 0xFF])

    d1 = FileHash(file=_write(tmp_path, "a.bin", original)).create_integrity()
    d2 = FileHash(file=_write(tmp_path, "b.bin", modified)).create_integrity()

    assert d1 != d2


def test_identical_content_in_different_files_gives_same_digest(tmp_path):
    content = os.urandom(5000)
    d1 = FileHash(file=_write(tmp_path, "one.tif", content)).create_integrity()
    d2 = FileHash(file=_write(tmp_path, "two.tif", content)).create_integrity()
    assert d1 == d2


def test_filename_does_not_influence_digest(tmp_path):
    content = b"same content"
    d1 = FileHash(file=_write(tmp_path, "name_a.tif", content)).create_integrity()
    d2 = FileHash(
        file=_write(tmp_path, "totally_other.dat", content)
    ).create_integrity()
    assert d1 == d2


def test_sidecar_aux_xml_is_not_part_of_digest(tmp_path):
    path = _write(tmp_path, "survey.tif", b"raster")
    before = FileHash(file=path).create_integrity()

    _write(tmp_path, "survey.tif.aux.xml", b"<PAMDataset/>")
    after = FileHash(file=path).create_integrity()

    assert before == after


def test_digest_reflects_file_changes_between_calls(tmp_path):
    path = _write(tmp_path, "mutable.tif", b"version 1")
    hasher = FileHash(file=path)
    first = hasher.create_integrity()

    with open(path, "wb") as fh:
        fh.write(b"version 2")

    assert hasher.create_integrity() != first


def test_file_is_not_modified(hasher, small_file):
    mtime_before = os.stat(small_file).st_mtime_ns
    with open(small_file, "rb") as fh:
        content_before = fh.read()

    hasher.create_integrity()

    assert os.stat(small_file).st_mtime_ns == mtime_before
    with open(small_file, "rb") as fh:
        assert fh.read() == content_before


def test_file_removed_after_construction_raises(tmp_path):
    path = _write(tmp_path, "gone.tif", b"data")
    hasher = FileHash(file=path)
    os.remove(path)

    with pytest.raises(FileNotFoundError):
        hasher.create_integrity()


def test_directory_instead_of_file_raises(tmp_path):
    hasher = FileHash(file=str(tmp_path))
    with pytest.raises((IsADirectoryError, PermissionError)):
        hasher.create_integrity()
