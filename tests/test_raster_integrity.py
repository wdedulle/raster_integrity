#!/usr/bin/env python

import hashlib
import os
import sys

import numpy as np
import pytest
from osgeo import gdal, osr

import raster_integrity.setup as cm

gdal.UseExceptions()

GT = (150000.0, 1.0, 0.0, 200000.0, 0.0, -1.0)
EPSG = 31370  # Belgian Lambert 72


# --------------------------------------------------------------------------
# Helpers & fixtures
# --------------------------------------------------------------------------
def make_raster(path, data, nodata=None, gt=GT, epsg=EPSG):
    rows, cols = data.shape
    ds = gdal.GetDriverByName("GTiff").Create(
        str(path), cols, rows, 1, gdal.GDT_Float32
    )
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(data)
    band.FlushCache()
    ds = None
    return str(path)


def normal_data():
    rng = np.random.default_rng(42)
    return rng.uniform(-20, 0, size=(10, 10)).astype(np.float32)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_nodata(path):
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    ds = None
    return nodata


@pytest.fixture(autouse=True)
def restore_gdal_config():
    keys = ("GDAL_PAM_ENABLED", "GDAL_GEOREF_SOURCES")
    saved = {k: gdal.GetConfigOption(k) for k in keys}
    yield
    for k, v in saved.items():
        gdal.SetConfigOption(k, v)


@pytest.fixture
def tif(tmp_path):
    return make_raster(tmp_path / "normal.tif", normal_data())


# --------------------------------------------------------------------------
# create_metadata_file: .aux.xml behavior
# --------------------------------------------------------------------------
def test_creates_aux_xml(tif):
    assert not os.path.exists(f"{tif}.aux.xml")
    cm.create_metadata_file(tif)
    assert os.path.exists(f"{tif}.aux.xml")


def test_existing_aux_xml_is_replaced(tif):
    aux = f"{tif}.aux.xml"
    with open(aux, "w") as f:
        f.write("<STALE_MARKER/>")

    cm.create_metadata_file(tif)

    assert os.path.exists(aux)
    with open(aux) as f:
        assert "STALE_MARKER" not in f.read()


def test_original_raster_is_not_modified(tif):
    before = sha256(tif)
    cm.create_metadata_file(tif)
    assert sha256(tif) == before


def test_nonexistent_file_raises(tmp_path):
    with pytest.raises(RuntimeError):
        cm.create_metadata_file(str(tmp_path / "bestaat_niet.tif"))


# --------------------------------------------------------------------------
# create_metadata_file: content of metadata
# --------------------------------------------------------------------------
def test_corporation_metadata_written(tif):
    cm.create_metadata_file(tif)
    ds = gdal.Open(tif, gdal.GA_ReadOnly)
    assert ds.GetMetadataItem("Corporation") == "CORP"
    ds = None


def test_aux_xml_contains_corporation(tif):
    cm.create_metadata_file(tif)
    with open(f"{tif}.aux.xml", encoding="utf-8") as f:
        content = f.read()
    assert "Corporation" in content
    assert "CORP" in content


def test_srs_and_geotransform_preserved(tif):
    ds = gdal.Open(tif, gdal.GA_ReadOnly)
    srs_before = osr.SpatialReference(wkt=ds.GetProjection())
    gt_before = ds.GetGeoTransform()
    ds = None

    cm.create_metadata_file(tif)

    ds = gdal.Open(tif, gdal.GA_ReadOnly)
    srs_after = osr.SpatialReference(wkt=ds.GetProjection())
    gt_after = ds.GetGeoTransform()
    ds = None

    assert srs_after.IsSame(srs_before)
    assert gt_after == pytest.approx(gt_before)


def test_statistics_written_to_pam(tif):
    cm.create_metadata_file(tif)
    ds = gdal.Open(tif, gdal.GA_ReadOnly)
    md = ds.GetRasterBand(1).GetMetadata()
    ds = None

    for key in ("STATISTICS_MINIMUM", "STATISTICS_MAXIMUM", "STATISTICS_MEAN"):
        assert key in md

    data = normal_data()
    assert float(md["STATISTICS_MINIMUM"]) == pytest.approx(float(data.min()), abs=1e-4)
    assert float(md["STATISTICS_MAXIMUM"]) == pytest.approx(float(data.max()), abs=1e-4)


# --------------------------------------------------------------------------
# create_metadata_file: no-data detection
# --------------------------------------------------------------------------
def test_no_nodata_set_for_normal_values(tif):
    cm.create_metadata_file(tif)
    assert read_nodata(tif) is None


def test_existing_nodata_is_kept(tmp_path):
    data = normal_data()
    data[0, 0] = -9999
    path = make_raster(tmp_path / "with_nd.tif", data, nodata=-9999)

    cm.create_metadata_file(path)

    assert read_nodata(path) == pytest.approx(-9999)


def test_large_max_detected_as_nodata(tmp_path):
    data = normal_data()
    data[3, 3] = 1e10
    path = make_raster(tmp_path / "big_max.tif", data)

    cm.create_metadata_file(path)

    assert read_nodata(path) == pytest.approx(1e10)


def test_very_small_min_detected_as_nodata(tmp_path):
    data = normal_data()
    data[3, 3] = -3.4e38
    path = make_raster(tmp_path / "small_min.tif", data)

    cm.create_metadata_file(path)

    assert read_nodata(path) == pytest.approx(-3.4e38, rel=1e-3)


def test_min_takes_precedence_when_both_extremes_present(tmp_path):
    """Documenteert het huidige gedrag: de min-check overschrijft de max-check."""
    data = normal_data()
    data[0, 0] = 1e10
    data[1, 1] = -1e10
    path = make_raster(tmp_path / "both.tif", data)

    cm.create_metadata_file(path)

    assert read_nodata(path) == pytest.approx(-1e10)


def test_detected_nodata_is_excluded_from_statistics(tmp_path):
    data = normal_data()
    data[3, 3] = 1e10
    path = make_raster(tmp_path / "stats_nd.tif", data)

    cm.create_metadata_file(path)

    ds = gdal.Open(path, gdal.GA_ReadOnly)
    md = ds.GetRasterBand(1).GetMetadata()
    ds = None

    real_max = float(np.delete(data.ravel(), 3 * 10 + 3).max())
    assert float(md["STATISTICS_MAXIMUM"]) == pytest.approx(real_max, abs=1e-4)


@pytest.mark.parametrize("value", [99999, 50000, 0])
def test_values_within_thresholds_are_not_nodata(tmp_path, value):
    data = normal_data()
    data[3, 3] = value
    path = make_raster(tmp_path / f"within_{value}.tif", data)

    cm.create_metadata_file(path)

    assert read_nodata(path) is None


# --------------------------------------------------------------------------
# create_metadata_file: GDAL config will be restored
# --------------------------------------------------------------------------
def test_config_options_restored_when_previously_set(tif):
    gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
    gdal.SetConfigOption("GDAL_GEOREF_SOURCES", "INTERNAL")

    cm.create_metadata_file(tif)

    assert gdal.GetConfigOption("GDAL_PAM_ENABLED") == "NO"
    assert gdal.GetConfigOption("GDAL_GEOREF_SOURCES") == "INTERNAL"


def test_config_options_restored_when_previously_unset(tif):
    gdal.SetConfigOption("GDAL_PAM_ENABLED", None)
    gdal.SetConfigOption("GDAL_GEOREF_SOURCES", None)

    cm.create_metadata_file(tif)

    assert gdal.GetConfigOption("GDAL_PAM_ENABLED") is None
    assert gdal.GetConfigOption("GDAL_GEOREF_SOURCES") is None


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------
def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["prog", *args])
    cm.main()


def test_main_requires_file_argument(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch)
    assert exc.value.code == 2
    assert "--file" in capsys.readouterr().err


def test_main_missing_file_exits_with_1(monkeypatch, capsys, tmp_path):
    missing = str(tmp_path / "nope.tif")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--file", missing)
    assert exc.value.code == 1
    assert "ERROR: File not found" in capsys.readouterr().out


def test_main_creates_aux_and_prints_metadata(monkeypatch, capsys, tif):
    run_main(monkeypatch, "--file", tif)
    out = capsys.readouterr().out

    assert os.path.exists(f"{tif}.aux.xml")
    assert "GTiff" in out
    assert tif in out
    assert "DATASET METADATA" in out
    assert "BAND 1 METADATA" in out
    assert "CORP" in out
    assert "STATISTICS_MAXIMUM" in out


def test_main_short_flag(monkeypatch, capsys, tif):
    run_main(monkeypatch, "-f", tif)
    assert os.path.exists(f"{tif}.aux.xml")
