from osgeo import gdal
from pathlib import Path
import argparse, os, sys

gdal.UseExceptions()


def create_metadata_file(file_path, metadata=None):
    if os.path.exists(f"{file_path}.aux.xml"):
        os.remove(f"{file_path}.aux.xml")
    if metadata is not None:
        for key, value in metadata.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Invalid metadata-key: {key!r}")
            if value is None:
                raise ValueError(f"Metadata-value for '{key}' is empty")

    gdalPamEnabled = gdal.GetConfigOption("GDAL_PAM_ENABLED")
    gdalGeorefSrcs = gdal.GetConfigOption("GDAL_GEOREF_SOURCES")

    gdal.SetConfigOption("GDAL_PAM_ENABLED", "YES")
    gdal.SetConfigOption("GDAL_GEOREF_SOURCES", "PAM,INTERNAL")

    ds = gdal.Open(file_path, gdal.GA_ReadOnly)

    srs = ds.GetProjection()
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()

    if nodata == None:
        max_val = band.GetMaximum()
        min_val = band.GetMinimum()
        # Compute if not available
        if max_val is None or min_val is None:
            # False means calculate on full resolution
            min_val, max_val = band.ComputeRasterMinMax(False)

        # make decision - first max at last min (min is prior)
        if max_val > 99999:
            nodata = max_val
        if min_val < -9999:
            nodata = min_val

    ds = None

    ds2 = gdal.OpenEx(
        file_path,
        gdal.OF_RASTER,
        open_options=["GEOREF_SOURCES=PAM"],  # PAM has priority
    )
    if metadata:
        for key, value in metadata.items():
            ds2.SetMetadataItem(key, str(value))
    ds2.SetProjection(srs)
    ds2.SetGeoTransform(gt)
    if nodata is not None:
        ds2.GetRasterBand(1).SetNoDataValue(nodata)
    ds2.GetRasterBand(1).ComputeStatistics(False)

    ds2.FlushCache()
    ds2 = None
    gdal.SetConfigOption("GDAL_PAM_ENABLED", gdalPamEnabled)
    gdal.SetConfigOption("GDAL_GEOREF_SOURCES", gdalGeorefSrcs)


def parse_meta(item):
    if "=" not in item:
        raise argparse.ArgumentTypeError(f"Expected KEY=VALUE, given: {item}")
    key, value = item.split("=", 1)
    return key.strip(), value.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Enforce raster data to include metadata, ie: raster_integrity.setup -f raster.tif -m Corporation='CORP' Survey_Year=2025 Datum=LAT"
    )

    parser.add_argument(
        "--meta",
        "-m",
        action="append",
        type=parse_meta,
        help="Metadata as KEY=VALUE (repeatable ie: -m Corporation='CORP' Survey_Year=2025 Datum=LAT)",
    )

    parser.add_argument(
        "--file", "-f", required=True, help="Raster file to create a metadatafile"
    )

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}")
        sys.exit(1)
    metadata = dict(args.meta) if args.meta else None
    create_metadata_file(args.file, metadata)

    gdal.SetConfigOption("GDAL_PAM_ENABLED", "YES")
    ds = gdal.Open(args.file, gdal.GA_ReadOnly)
    band = ds.GetRasterBand(1)
    band_metadata = band.GetMetadata()
    print("+" + "-" * len(ds.GetDriver().GetName()) + "+")
    print("|" + ds.GetDriver().GetName() + "|")
    print("+" + "-" * len(ds.GetDriver().GetName()) + "+")
    print(args.file)
    print("-" * len(args.file))
    print("DATASET METADATA")
    print(ds.GetMetadata())
    print("BAND 1 METADATA")
    print(band_metadata)
    ds.FlushCache()
    ds = None
