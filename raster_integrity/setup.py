from osgeo import gdal
from pathlib import Path
import argparse, os, sys

gdal.UseExceptions() 

def create_metadata_file(file_path):
    if os.path.exists(f"{file_path}.aux.xml"):
        os.remove(f"{file_path}.aux.xml")

    gdalPamEnabled = gdal.GetConfigOption("GDAL_PAM_ENABLED")
    gdalGeorefSrcs = gdal.GetConfigOption("GDAL_GEOREF_SOURCES")
    
    gdal.SetConfigOption("GDAL_PAM_ENABLED", "YES")
    gdal.SetConfigOption("GDAL_GEOREF_SOURCES", "PAM,INTERNAL")
    # Open read-only -> GDAL kan niet intern schrijven
    # -> valt terug op .aux.xml voor alle metadata
    ds = gdal.Open(file_path, gdal.GA_ReadOnly)

    # Extraheer huidige waarden
    srs  = ds.GetProjection()
    gt   = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    nd   = band.GetNoDataValue()
    #eerste controle op no data values
    #bekijk de max en min values, als die zeer grote afwijking bevatten,
    #  dan is 1 of van de waarden een no data value kandidaat
    
    if nd == None:
        max_val = band.GetMaximum()
        min_val = band.GetMinimum()
        # Compute if not available
        if max_val is None or min_val is None:
            # False means calculate on full resolution
            min_val, max_val = band.ComputeRasterMinMax(False)

        # make decision - first max at last min (min is prior)
        if max_val > 99999:
            nd = max_val
        if min_val < -9999:
            nd = min_val

    # Sluit het bestand
    ds = None

    # Heropen via gdal_edit equivalent: gebruik gdal.Translate
    # naar /vsimem/ om PAM te forceren via update op read-only
    ds2 = gdal.OpenEx(
        file_path,
        gdal.OF_RASTER,
        open_options=["GEOREF_SOURCES=PAM"]  # PAM heeft prioriteit
    )
    ds2.SetMetadataItem("Corporation", "Vlaamse Hydrografie")
    # Schrijf SRS en GeoTransform expliciet naar PAM
    ds2.SetProjection(srs)
    ds2.SetGeoTransform(gt)
    if nd is not None:
        ds2.GetRasterBand(1).SetNoDataValue(nd)
    ds2.GetRasterBand(1).ComputeStatistics(False)

    ds2.FlushCache()
    ds2 = None
    gdal.SetConfigOption("GDAL_PAM_ENABLED", gdalPamEnabled)
    gdal.SetConfigOption("GDAL_GEOREF_SOURCES", gdalGeorefSrcs)

def main():
    parser = argparse.ArgumentParser(
        description="Evaluatie van integriteitscontrolemethoden voor bathymetrische data"
    )
    parser.add_argument(
        "--file", "-f", required=True,
        help="Raster file to create a metadatafile"
    )

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}")
        sys.exit(1)

    create_metadata_file(args.file)

    gdal.SetConfigOption("GDAL_PAM_ENABLED", "YES")
    ds = gdal.Open(args.file, gdal.GA_ReadOnly)
    band = ds.GetRasterBand(1)
    band_metadata = band.GetMetadata()
    print("+" + "-"*len(ds.GetDriver().GetName()) + "+")
    print("|"+ ds.GetDriver().GetName() +"|")
    print("+" + "-"*len(ds.GetDriver().GetName()) + "+")
    print(args.file)
    print("-"*len(args.file))
    print("DATASET METADATA")
    print(ds.GetMetadata())
    print("BAND 1 METADATA")
    print(band_metadata)
    ds.FlushCache()
    ds = None
