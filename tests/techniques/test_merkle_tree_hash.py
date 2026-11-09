"""
test_merkle_tree_hash.py
========================
Pytest-tests for MerkleTreeInmemoryHash, MerkleTreeSqliteHash and
MerkleTreeInmemoryRobustHash.

Required: GDAL (osgeo), NumPy en pymerkle.
"""

import gc
import os
import sqlite3

import numpy as np
import pytest
from osgeo import gdal
from pymerkle import SqliteTree

from raster_integrity.techniques import merkle_tree_hash as merkle_module
from raster_integrity.techniques.merkle_tree_hash import (
    MerkleTreeInmemoryHash,
    MerkleTreeInmemoryRobustHash,
    MerkleTreeSqliteHash,
)

gdal.UseExceptions()

NODATA = -9999.0
ROWS, COLS = 40, 48


def make_raster(
    path,
    array,
    nodata=None,
    ds_meta=None,
    band_meta=None,
    options=None,
    geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
    second_band=None,
):
    rows, cols = array.shape
    nbands = 2 if second_band is not None else 1
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), cols, rows, nbands, gdal.GDT_Float32, options or [])
    ds.SetGeoTransform(geotransform)

    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(array.astype(np.float32))

    for key, value in (ds_meta or {}).items():
        ds.SetMetadataItem(key, value)
    for key, value in (band_meta or {}).items():
        band.SetMetadataItem(key, value)

    if second_band is not None:
        ds.GetRasterBand(2).WriteArray(second_band.astype(np.float32))

    ds.FlushCache()
    band = None
    ds = None
    return str(path)


@pytest.fixture
def values():
    rng = np.random.default_rng(42)
    return rng.uniform(1, 50, (ROWS, COLS)).astype(np.float32)


@pytest.fixture
def raster(tmp_path, values):
    return make_raster(tmp_path / "survey.tif", values)


_OPEN_TREES = []


class TrackedSqliteTree(SqliteTree):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _OPEN_TREES.append(self)


def _close_connections(obj):
    for value in list(getattr(obj, "__dict__", {}).values()):
        if isinstance(value, sqlite3.Connection):
            try:
                value.close()
            except sqlite3.Error:
                pass


def _release_trees():
    while _OPEN_TREES:
        _close_connections(_OPEN_TREES.pop())
    gc.collect()


@pytest.fixture(autouse=True)
def _track_sqlite_trees(monkeypatch):
    _OPEN_TREES.clear()
    monkeypatch.setattr(merkle_module, "SqliteTree", TrackedSqliteTree)
    yield
    _release_trees()


def _create(hasher, **kwargs):
    try:
        return hasher.create_integrity(**kwargs)
    finally:
        _release_trees()


def _fp(cls, path, **kwargs):
    return _create(cls(file=path), **kwargs)


class FakeTree:

    def __init__(self):
        self.entries = []

    def append_entry(self, data):
        self.entries.append(data)


ALL_CLASSES = [
    MerkleTreeInmemoryHash,
    MerkleTreeSqliteHash,
    MerkleTreeInmemoryRobustHash,
]


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_constructor_requires_file(cls):
    with pytest.raises(TypeError, match="file"):
        cls()


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_constructor_rejects_nonexistent_file(cls, tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        cls(file=str(tmp_path / "missing.tif"))


def test_labels(raster):
    assert MerkleTreeInmemoryHash(file=raster).label() == "merkle_tree_inmemory_hash"
    assert MerkleTreeSqliteHash(file=raster).label() == "merkle_tree_sqlite_hash"


def test_robust_label_contains_precision(raster):
    hasher = MerkleTreeInmemoryRobustHash(file=raster)
    hasher.create_integrity(precision=2)
    assert hasher.label() == "merkle_tree_robust_hash_p2"


def test_robust_label_default_precision_is_3(raster):
    hasher = MerkleTreeInmemoryRobustHash(file=raster)
    hasher.create_integrity()
    assert hasher.label() == "merkle_tree_robust_hash_p3"


def test_robust_label_before_create_integrity_raises(raster):
    # _precision wordt pas in create_integrity gezet
    hasher = MerkleTreeInmemoryRobustHash(file=raster)
    with pytest.raises(AttributeError):
        hasher.label()


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_fingerprint_is_sha256_hex_by_default(cls, raster):
    fp = _fp(cls, raster)
    assert isinstance(fp, str)
    assert len(fp) == 64
    int(fp, 16)


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_fingerprint_is_deterministic(cls, raster):
    assert _fp(cls, raster) == _fp(cls, raster)


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_default_algorithm_is_stored(cls, raster):
    hasher = cls(file=raster)
    _create(hasher)
    assert hasher._algorithm == "sha256"


@pytest.mark.parametrize("cls", ALL_CLASSES)
@pytest.mark.parametrize(
    "algorithm,hex_len", [("sha256", 64), ("sha512", 128), ("sha3_256", 64)]
)
def test_algorithm_selection(cls, raster, algorithm, hex_len):
    hasher = cls(file=raster)
    fp = _create(hasher, algorithm=algorithm)
    assert len(fp) == hex_len
    assert hasher._algorithm == algorithm


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_different_algorithms_give_different_fingerprints(cls, raster):
    assert _fp(cls, raster, algorithm="sha256") != _fp(cls, raster, algorithm="sha512")


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_algorithm_resets_to_default_on_next_call(cls, raster):
    hasher = cls(file=raster)
    _create(hasher, algorithm="sha512")
    fp = _create(hasher)
    assert hasher._algorithm == "sha256"
    assert len(fp) == 64


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_unknown_algorithm_raises(cls, raster):
    with pytest.raises(Exception):
        _create(cls(file=raster), algorithm="not-a-real-algorithm")


@pytest.mark.parametrize("cls", [MerkleTreeInmemoryHash, MerkleTreeSqliteHash])
def test_single_value_change_changes_fingerprint(cls, tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values)
    changed = values.copy()
    changed[ROWS // 2, COLS // 2] += 0.5
    b = make_raster(tmp_path / "b.tif", changed)

    assert _fp(cls, a) != _fp(cls, b)


def test_change_in_last_row_is_detected(tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values)
    changed = values.copy()
    changed[-1, -1] += 1.0
    b = make_raster(tmp_path / "b.tif", changed)

    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_row_order_matters(tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values)
    swapped = values.copy()
    swapped[[0, 1]] = swapped[[1, 0]]
    b = make_raster(tmp_path / "b.tif", swapped)

    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_same_values_in_different_files_give_same_fingerprint(tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values)
    b = make_raster(tmp_path / "other_name.tif", values)
    assert _fp(MerkleTreeInmemoryHash, a) == _fp(MerkleTreeInmemoryHash, b)


def test_negated_values_differ_for_regular_hash(tmp_path, values):
    a = make_raster(tmp_path / "pos.tif", values)
    b = make_raster(tmp_path / "neg.tif", -values)
    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_compression_does_not_change_fingerprint(tmp_path, values):
    plain = make_raster(tmp_path / "plain.tif", values)
    compressed = make_raster(
        tmp_path / "compressed.tif", values, options=["COMPRESS=DEFLATE", "PREDICTOR=3"]
    )
    assert _fp(MerkleTreeInmemoryHash, plain) == _fp(MerkleTreeInmemoryHash, compressed)


def test_tiling_does_not_change_fingerprint(tmp_path, values):
    plain = make_raster(tmp_path / "plain.tif", values)
    tiled = make_raster(
        tmp_path / "tiled.tif",
        values,
        options=["TILED=YES", "BLOCKXSIZE=16", "BLOCKYSIZE=16"],
    )
    assert _fp(MerkleTreeInmemoryHash, plain) == _fp(MerkleTreeInmemoryHash, tiled)


def test_geotransform_is_not_part_of_fingerprint(tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values)
    b = make_raster(
        tmp_path / "b.tif",
        values,
        geotransform=(500000.0, 0.5, 0.0, 5700000.0, 0.0, -0.5),
    )
    assert _fp(MerkleTreeInmemoryHash, a) == _fp(MerkleTreeInmemoryHash, b)


def test_second_band_is_not_part_of_fingerprint(tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values, second_band=np.zeros_like(values))
    b = make_raster(tmp_path / "b.tif", values, second_band=np.ones_like(values))
    assert _fp(MerkleTreeInmemoryHash, a) == _fp(MerkleTreeInmemoryHash, b)


def test_nodata_cells_are_removed_from_rows(tmp_path):
    a_arr = np.array([[1, NODATA, 3, 4]] * 4, dtype=np.float32)
    b_arr = np.array([[1, 3, NODATA, 4]] * 4, dtype=np.float32)
    a = make_raster(tmp_path / "a.tif", a_arr, nodata=NODATA)
    b = make_raster(tmp_path / "b.tif", b_arr, nodata=NODATA)

    assert _fp(MerkleTreeInmemoryHash, a) == _fp(MerkleTreeInmemoryHash, b)


def test_nodata_value_itself_does_not_leak_into_fingerprint(tmp_path):
    arr_a = np.array([[1, NODATA, 3]] * 3, dtype=np.float32)
    arr_b = np.array([[1, -1.0e6, 3]] * 3, dtype=np.float32)
    a = make_raster(tmp_path / "a.tif", arr_a, nodata=NODATA)
    b = make_raster(tmp_path / "b.tif", arr_b, nodata=-1.0e6)

    assert _fp(MerkleTreeInmemoryHash, a) == _fp(MerkleTreeInmemoryHash, b)


def test_without_nodata_value_all_cells_are_hashed(tmp_path):
    arr = np.array([[1, NODATA, 3]] * 3, dtype=np.float32)
    with_nodata = make_raster(tmp_path / "a.tif", arr, nodata=NODATA)
    without_nodata = make_raster(tmp_path / "b.tif", arr)

    assert _fp(MerkleTreeInmemoryHash, with_nodata) != _fp(
        MerkleTreeInmemoryHash, without_nodata
    )


def test_changing_valid_value_next_to_nodata_is_detected(tmp_path):
    a_arr = np.array([[1, NODATA, 3]] * 3, dtype=np.float32)
    b_arr = np.array([[1, NODATA, 3.5]] * 3, dtype=np.float32)
    a = make_raster(tmp_path / "a.tif", a_arr, nodata=NODATA)
    b = make_raster(tmp_path / "b.tif", b_arr, nodata=NODATA)

    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


@pytest.mark.parametrize("key", ["STATISTICS_MEAN", "Corporation_Owner"])
def test_selected_band_metadata_is_part_of_fingerprint(tmp_path, values, key):
    a = make_raster(tmp_path / "a.tif", values, band_meta={key: "1"})
    b = make_raster(tmp_path / "b.tif", values, band_meta={key: "2"})
    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_selected_dataset_metadata_is_part_of_fingerprint(tmp_path, values):
    a = make_raster(tmp_path / "a.tif", values, ds_meta={"STATISTICS_MINIMUM": "1"})
    b = make_raster(tmp_path / "b.tif", values, ds_meta={"STATISTICS_MINIMUM": "2"})
    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_other_metadata_is_ignored(tmp_path, values):
    a = make_raster(
        tmp_path / "a.tif", values, ds_meta={"FOO": "1"}, band_meta={"BAR": "x"}
    )
    b = make_raster(
        tmp_path / "b.tif", values, ds_meta={"FOO": "2"}, band_meta={"BAR": "y"}
    )
    plain = make_raster(tmp_path / "c.tif", values)

    fa = _fp(MerkleTreeInmemoryHash, a)
    assert fa == _fp(MerkleTreeInmemoryHash, b)
    assert fa == _fp(MerkleTreeInmemoryHash, plain)


def test_metadata_presence_changes_fingerprint(tmp_path, values):
    with_meta = make_raster(
        tmp_path / "a.tif", values, band_meta={"STATISTICS_MEAN": "1"}
    )
    plain = make_raster(tmp_path / "b.tif", values)
    assert _fp(MerkleTreeInmemoryHash, with_meta) != _fp(MerkleTreeInmemoryHash, plain)


def test_add_metadata_filters_sorts_and_formats():
    hasher = MerkleTreeInmemoryHash.__new__(MerkleTreeInmemoryHash)
    tree = FakeTree()
    metadata = [
        ("STATISTICS_MEAN", "1.5"),
        ("Corporation_x", "a"),
        ("OTHER", "z"),
        ("STATISTICS_MAXIMUM", "9"),
    ]

    hasher._addMetadataToTree(metadata, tree)

    assert tree.entries == [
        b"Corporation_x=a",
        b"STATISTICS_MAXIMUM=9",
        b"STATISTICS_MEAN=1.5",
    ]


def test_add_metadata_with_no_matching_keys_adds_nothing():
    hasher = MerkleTreeInmemoryHash.__new__(MerkleTreeInmemoryHash)
    tree = FakeTree()
    hasher._addMetadataToTree([("FOO", "1")], tree)
    assert tree.entries == []


def test_normalize_to_prec_is_identity_for_regular_hash():
    hasher = MerkleTreeInmemoryHash.__new__(MerkleTreeInmemoryHash)
    assert hasher._normalize_to_prec("12.123456") == "12.123456"
    assert hasher._normalize_to_prec(5) == 5


def test_inmemory_creates_no_database(raster):
    _fp(MerkleTreeInmemoryHash, raster)
    assert not os.path.exists(f"{raster}.db")


def test_inmemory_removes_stale_database(raster):
    db = f"{raster}.db"
    with open(db, "w") as fh:
        fh.write("stale")

    _fp(MerkleTreeInmemoryHash, raster)

    assert not os.path.exists(db)


def test_house_holding_without_database_is_fine(raster):
    MerkleTreeInmemoryHash(file=raster)._house_holding()


def test_sqlite_creates_database_next_to_dataset(raster):
    _fp(MerkleTreeSqliteHash, raster)
    assert os.path.isfile(f"{raster}.db")


def test_sqlite_fingerprint_equals_inmemory_fingerprint(tmp_path, values):
    meta = {"STATISTICS_MEAN": "25.5", "Corporation_Owner": "FH"}
    path = make_raster(tmp_path / "s.tif", values, nodata=NODATA, band_meta=meta)

    inmemory = _fp(MerkleTreeInmemoryHash, path)
    sqlite = _fp(MerkleTreeSqliteHash, path)

    assert inmemory == sqlite


def test_sqlite_can_be_run_twice_with_same_result(raster):
    first = _fp(MerkleTreeSqliteHash, raster)
    second = _fp(MerkleTreeSqliteHash, raster)
    assert first == second


def test_sqlite_database_holds_persisted_tree(tmp_path, values):
    meta = {"STATISTICS_MEAN": "25.5"}
    path = make_raster(tmp_path / "s.tif", values, band_meta=meta)

    fingerprint = _fp(MerkleTreeSqliteHash, path)

    tree = SqliteTree(f"{path}.db", algorithm="sha256")
    try:
        assert tree.get_state().hex() == fingerprint
        assert tree.get_size() == ROWS + 1
    finally:
        _close_connections(tree)


def test_sqlite_new_integrity_replaces_previous_database(tmp_path, values):
    path = make_raster(tmp_path / "s.tif", values)
    hasher = MerkleTreeSqliteHash(file=path)

    first = _create(hasher)
    second = _create(hasher)

    assert first == second

    tree = SqliteTree(f"{path}.db", algorithm="sha256")
    try:
        # zou de oude boom blijven staan, dan was de grootte 2 * ROWS
        assert tree.get_size() == ROWS
        assert tree.get_state().hex() == second
    finally:
        _close_connections(tree)


def test_sqlite_database_reflects_changed_raster_after_new_integrity(tmp_path, values):
    path = make_raster(tmp_path / "s.tif", values)
    old = _fp(MerkleTreeSqliteHash, path)

    make_raster_path = tmp_path / "s.tif"
    make_raster_path.unlink()
    make_raster(make_raster_path, values + 1.0)
    new = _fp(MerkleTreeSqliteHash, path)

    assert new != old
    tree = SqliteTree(f"{path}.db", algorithm="sha256")
    try:
        assert tree.get_state().hex() == new
        assert tree.get_size() == ROWS
    finally:
        _close_connections(tree)


def test_sqlite_removes_stale_database(raster):
    db = f"{raster}.db"
    with open(db, "w") as fh:
        fh.write("geen geldige sqlite-database")

    fingerprint = _fp(MerkleTreeSqliteHash, raster)

    assert len(fingerprint) == 64
    assert os.path.isfile(db)


def test_robust_normalize_rounds_and_takes_absolute_value():
    hasher = MerkleTreeInmemoryRobustHash.__new__(MerkleTreeInmemoryRobustHash)
    hasher._precision = 2
    assert hasher._normalize_to_prec("12.1234") == 12.12
    assert hasher._normalize_to_prec("-5.25") == 5.25
    assert hasher._normalize_to_prec(-5.2499999) == 5.25


def test_robust_normalize_keeps_non_numeric_values():
    hasher = MerkleTreeInmemoryRobustHash.__new__(MerkleTreeInmemoryRobustHash)
    hasher._precision = 3
    assert hasher._normalize_to_prec("FH") == "FH"


def test_robust_metadata_swaps_min_max_for_negative_mean():
    hasher = MerkleTreeInmemoryRobustHash.__new__(MerkleTreeInmemoryRobustHash)
    meta = {
        "STATISTICS_MEAN": "-5",
        "STATISTICS_MINIMUM": "-10",
        "STATISTICS_MAXIMUM": "-1",
    }
    result = hasher._robust_metadata(meta)
    assert result["STATISTICS_MINIMUM"] == "-1"
    assert result["STATISTICS_MAXIMUM"] == "-10"


def test_robust_metadata_unchanged_for_positive_mean():
    hasher = MerkleTreeInmemoryRobustHash.__new__(MerkleTreeInmemoryRobustHash)
    meta = {
        "STATISTICS_MEAN": "5",
        "STATISTICS_MINIMUM": "1",
        "STATISTICS_MAXIMUM": "10",
    }
    assert hasher._robust_metadata(dict(meta)) == meta


def test_robust_metadata_without_mean_is_untouched():
    hasher = MerkleTreeInmemoryRobustHash.__new__(MerkleTreeInmemoryRobustHash)
    meta = {"STATISTICS_MINIMUM": "-10", "STATISTICS_MAXIMUM": "-1"}
    assert hasher._robust_metadata(dict(meta)) == meta


def test_robust_ignores_differences_beyond_precision(tmp_path):
    a_arr = np.full((8, 8), 12.1234, dtype=np.float32)
    b_arr = np.full((8, 8), 12.1231, dtype=np.float32)
    a = make_raster(tmp_path / "a.tif", a_arr)
    b = make_raster(tmp_path / "b.tif", b_arr)

    assert _fp(MerkleTreeInmemoryRobustHash, a, precision=3) == _fp(
        MerkleTreeInmemoryRobustHash, b, precision=3
    )


def test_regular_hash_detects_the_same_small_difference(tmp_path):
    a_arr = np.full((8, 8), 12.1234, dtype=np.float32)
    b_arr = np.full((8, 8), 12.1231, dtype=np.float32)
    a = make_raster(tmp_path / "a.tif", a_arr)
    b = make_raster(tmp_path / "b.tif", b_arr)

    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_robust_detects_real_content_changes(tmp_path):
    a = make_raster(tmp_path / "a.tif", np.full((8, 8), 12.123, dtype=np.float32))
    b = make_raster(tmp_path / "b.tif", np.full((8, 8), 12.456, dtype=np.float32))

    assert _fp(MerkleTreeInmemoryRobustHash, a) != _fp(MerkleTreeInmemoryRobustHash, b)


def test_robust_higher_precision_is_more_sensitive(tmp_path):
    a = make_raster(tmp_path / "a.tif", np.full((8, 8), 12.1234, dtype=np.float32))
    b = make_raster(tmp_path / "b.tif", np.full((8, 8), 12.1231, dtype=np.float32))
    # p=3: 12.123 == 12.123 ; p=4: 12.1234 != 12.1231
    assert _fp(MerkleTreeInmemoryRobustHash, a, precision=3) == _fp(
        MerkleTreeInmemoryRobustHash, b, precision=3
    )
    assert _fp(MerkleTreeInmemoryRobustHash, a, precision=4) != _fp(
        MerkleTreeInmemoryRobustHash, b, precision=4
    )


def test_robust_rounding_boundary_is_not_a_true_tolerance(tmp_path):
    a = make_raster(tmp_path / "a.tif", np.full((8, 8), 12.1234, dtype=np.float32))
    b = make_raster(tmp_path / "b.tif", np.full((8, 8), 12.1236, dtype=np.float32))

    assert _fp(MerkleTreeInmemoryRobustHash, a, precision=3) != _fp(
        MerkleTreeInmemoryRobustHash, b, precision=3
    )


def test_robust_is_sign_insensitive(tmp_path, values):
    pos = make_raster(tmp_path / "pos.tif", values)
    neg = make_raster(tmp_path / "neg.tif", -values)

    assert _fp(MerkleTreeInmemoryRobustHash, pos) == _fp(
        MerkleTreeInmemoryRobustHash, neg
    )


def test_robust_sign_convention_with_statistics_metadata(tmp_path, values):
    pos_meta = {
        "STATISTICS_MEAN": "5",
        "STATISTICS_MINIMUM": "1",
        "STATISTICS_MAXIMUM": "10",
    }
    neg_meta = {
        "STATISTICS_MEAN": "-5",
        "STATISTICS_MINIMUM": "-10",
        "STATISTICS_MAXIMUM": "-1",
    }
    pos = make_raster(tmp_path / "pos.tif", values, band_meta=pos_meta)
    neg = make_raster(tmp_path / "neg.tif", -values, band_meta=neg_meta)

    assert _fp(MerkleTreeInmemoryRobustHash, pos) == _fp(
        MerkleTreeInmemoryRobustHash, neg
    )


def test_robust_metadata_rounding_is_applied(tmp_path, values):
    a = make_raster(
        tmp_path / "a.tif", values, band_meta={"STATISTICS_MEAN": "5.00001"}
    )
    b = make_raster(
        tmp_path / "b.tif", values, band_meta={"STATISTICS_MEAN": "5.00002"}
    )

    assert _fp(MerkleTreeInmemoryRobustHash, a) == _fp(MerkleTreeInmemoryRobustHash, b)
    assert _fp(MerkleTreeInmemoryHash, a) != _fp(MerkleTreeInmemoryHash, b)


def test_robust_nodata_is_masked(tmp_path):
    a_arr = np.array([[1.5, NODATA, 3.5]] * 4, dtype=np.float32)
    b_arr = np.array([[1.5, 3.5, NODATA]] * 4, dtype=np.float32)
    a = make_raster(tmp_path / "a.tif", a_arr, nodata=NODATA)
    b = make_raster(tmp_path / "b.tif", b_arr, nodata=NODATA)

    assert _fp(MerkleTreeInmemoryRobustHash, a) == _fp(MerkleTreeInmemoryRobustHash, b)


def test_robust_and_regular_fingerprints_differ(tmp_path):
    path = make_raster(tmp_path / "a.tif", np.full((8, 8), 12.123456, dtype=np.float32))
    assert _fp(MerkleTreeInmemoryHash, path) != _fp(MerkleTreeInmemoryRobustHash, path)


def test_robust_precision_is_stored(raster):
    hasher = MerkleTreeInmemoryRobustHash(file=raster)
    hasher.create_integrity(precision=2)
    assert hasher._precision == 2


def test_robust_precision_resets_to_default_on_next_call(raster):
    hasher = MerkleTreeInmemoryRobustHash(file=raster)
    hasher.create_integrity(precision=2)
    hasher.create_integrity()
    assert hasher._precision == 3


def test_robust_creates_no_database(raster):
    _fp(MerkleTreeInmemoryRobustHash, raster)
    assert not os.path.exists(f"{raster}.db")


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_file_that_gdal_cannot_open_raises(cls, tmp_path):
    bad = tmp_path / "not_a_raster.tif"
    bad.write_text("dit is geen raster")

    with pytest.raises((RuntimeError, FileNotFoundError)):
        _create(cls(file=str(bad)))


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_file_removed_after_construction_raises(cls, tmp_path, values):
    path = make_raster(tmp_path / "gone.tif", values)
    hasher = cls(file=path)
    os.remove(path)

    with pytest.raises((RuntimeError, FileNotFoundError)):
        _create(hasher)


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_source_raster_is_not_modified(cls, raster):
    with open(raster, "rb") as fh:
        before = fh.read()

    _create(cls(file=raster))

    with open(raster, "rb") as fh:
        assert fh.read() == before
