"""
merkle_tree_hash.py
===================
Content-based integrity hashing of raster datasets with a Merkle tree.

Where a plain file hash (see FileHash) fingerprints the stored bytes of a
file, the classes in this module fingerprint the *content* of a raster: the
pixel values of the first band, read through GDAL. Every raster row becomes
one leaf of a Merkle tree (a binary tree in which every node is the hash of
its children). The root of the tree, hex-encoded, is the integrity value of
the dataset. This provides:

    - Format independence: the same values stored with a different
      compression or tiling yield the same fingerprint
    - Low memory use: the raster is read and hashed row by row
    - Change localisation: a persisted tree can be used to find which rows
      changed, or to prove that a row is part of the dataset
    - Tolerance (robust variant): insensitive to small rounding differences

Classes:
    MerkleTreeInmemoryHash
        Tree kept in memory. Nothing is written to disk.
    MerkleTreeSqliteHash
        Same fingerprint, but the tree is persisted in a SQLite database next
        to the dataset ("<file>.db"). Suited when the tree is needed after
        the calculation, for instance to generate proofs.
    MerkleTreeInmemoryRobustHash
        Rounds values before hashing, so that small numerical differences do
        not change the fingerprint (see "Robust hashing").

What is hashed (in this order):
    1. Dataset metadata items whose key starts with "STATISTICS" or
       "Corporation", sorted by key and stored as "key=value"
    2. The same selection from the metadata of band 1
    3. For each raster row: the values with NoData removed, as float32 bytes

    Not part of the fingerprint: georeferencing (geotransform, CRS), other
    bands, other metadata, and the position of NoData cells within a row.

Robust hashing:
    Before hashing, values are rounded to `precision` decimals (default 3)
    and converted to absolute values. The sign-insensitivity makes the
    fingerprint independent of the sign convention (e.g. depths stored as
    positive or negative numbers). For datasets with a negative mean,
    STATISTICS_MINIMUM and STATISTICS_MAXIMUM are swapped accordingly.

        12.123 == 12.1234555    (precision=3)
        12.123 != 12.456

    Limitations:
    - Rounding is not a true tolerance: two values that differ by less than
      10**-precision can still fall on different sides of a rounding
      boundary and produce different fingerprints.
    - A value cannot be distinguished from its negative, so the robust
      variant is only meaningful for datasets whose values share one sign.

Difference from a file hash:
    File hash:   digest of the stored bytes -> proves the file is unchanged
    Merkle hash: digest of the raster values -> proves the data is unchanged,
                 even if the file was rewritten (e.g. recompressed)

Use at Flemish Hydrography:
    - Fixity checks on archived bathymetric rasters (e.g. GeoTIFF)
    - Verifying that a dataset kept its values after format conversion
    - Producing the fingerprints that are timestamped (RFC 3161) or listed
      in a BagIt manifest

Requires: GDAL (osgeo), NumPy and pymerkle.

Usage:
    hasher = MerkleTreeInmemoryHash(algorithm="sha256")

    # Create the fingerprint of a raster
    fingerprint = hasher.create_integrity("dataset.tif")

    # Verify a raster against a stored fingerprint
    ok = hasher.verify("dataset.tif", integrity=fingerprint)

    # Tolerant of rounding differences beyond the third decimal
    robust = MerkleTreeInmemoryRobustHash(precision=3)
    fingerprint = robust.create_integrity("dataset.tif")
"""

from osgeo import gdal
import numpy as np
from pymerkle import SqliteTree, InmemoryTree
import hashlib
import sys
import os

gdal.UseExceptions()


class MerkleTreeInmemoryHash:
    def __init__(self, **kwargs):
        """
        Parameters
        ----------
        algorithm : str
            kind of algorithm to used for creating hash key
            standard: "sha256"
        """
        self._algorithm = "sha256"
        if "algorithm" in kwargs:
            self._algorithm = kwargs["algorithm"]

    def _getDatasource(self, url):
        ds = gdal.Open(url)
        if ds is None:
            raise FileNotFoundError(f"GDAL cannot open file: {url}")
        return ds

    def _getMerkleTree(self, url="output.xyz"):
        self.house_holding(url)
        return InmemoryTree(algorithm=self._algorithm)

    def _normalize_to_prec(self, value):
        return value

    def _addMetadataToTree(self, metadata, tree):
        # ADDING metadata
        # Sorted, be sure all metadata items are stored in the same way
        # Dictionary sort is not guaranteed
        filtered = sorted(
            (
                (k, self._normalize_to_prec(v))
                for k, v in metadata
                if k.startswith("STATISTICS") or k.startswith("Corporation")
            ),
            key=lambda x: x[0],  # sorteer op key
        )

        for meta_key, meta_value in filtered:
            tree.append_entry(f"{meta_key}={meta_value}".encode("utf-8"))

    def label(self):
        return "merkle_tree_inmemory_hash"

    def house_holding(self, url="output.xyz"):
        db_path = f"{url}.db"
        if os.path.exists(db_path):
            os.remove(db_path)

    def verify(self, url="output.xyz", integrity=""):
        return self.create_integrity(url) == integrity

    def create_integrity(self, url="output.xyz"):
        ds = self._getDatasource(url)
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()

        cols = ds.RasterXSize
        rows = ds.RasterYSize

        tree = self._getMerkleTree(f"{url}")

        # ADDING metadata
        self._addMetadataToTree(ds.GetMetadata().items(), tree)
        self._addMetadataToTree(band.GetMetadata().items(), tree)

        for y in range(rows):
            row = band.ReadAsArray(0, y, cols, 1)[0]
            # mask nodata
            if nodata is not None:
                row = row[row != nodata]
            # No X/Y, no geotransform, only structure + value
            packed = row.astype(np.float32).tobytes()
            tree.append_entry(packed)
        root = tree.get_state()
        # band.SetMetadataItem("fingerprint", root.hex())
        ds = None
        band = None
        return root.hex()


class MerkleTreeSqliteHash(MerkleTreeInmemoryHash):
    def label(self):
        return "merkle_tree_sqlite_hash"

    def _getMerkleTree(self, url="output.xyz"):
        self.house_holding(url)
        return SqliteTree(f"{url}.db", algorithm=self._algorithm)


class MerkleTreeInmemoryRobustHash(MerkleTreeInmemoryHash):
    """
    Merkle Tree integriteitscontrole with robust hashing.

    The difference with regular hashing:
        - Values will be rounded on `precision` decimals before hashing.
          It makes the hash tolerant for non-content changes such as:
              12.123     == 12.1234555  (precision=3)
              -5.25      == -5.2499999  (precision=2)
          It detects real content changes:
              12.123     != 12.456
    """

    def __init__(self, **kwargs):
        """
        Parameters
        ----------
        algorithm : str
            kind of algorithm to used for creating hash key
            standard: "sha256"
        precision : int
            Number of decimals to be rounded before hashing.
            High value = sensitive for small changes.
            Low value  = more tolerant for rounding differences.

            Recommendation for raster data:
                precision=2 -> tolerant up to 0.01m   (ie. after lossy compression)
                precision=3 -> tolerant up to 0.001m  (recommended standard)
                precision=4 -> tolerant up to 0.0001m (strict)
        """
        self._algorithm = "sha256"
        if "algorithm" in kwargs:
            self._algorithm = kwargs["algorithm"]

        self._precision = 3
        if "precision" in kwargs:
            self._precision = kwargs["precision"]

    def label(self):
        return f"merkle_tree_robust_hash_p{self._precision}"

    def _normalize_to_prec(self, value):
        try:
            return abs(round(float(value), self._precision))
        except ValueError:
            return value

    def _robust_metadata(self, metadata):
        if "STATISTICS_MEAN" in metadata and float(metadata["STATISTICS_MEAN"]) < 0:
            new_min = metadata["STATISTICS_MAXIMUM"]
            metadata["STATISTICS_MAXIMUM"] = metadata["STATISTICS_MINIMUM"]
            metadata["STATISTICS_MINIMUM"] = new_min
        return metadata

    def create_integrity(self, url="output.xyz"):
        ds = self._getDatasource(url)
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()

        cols = ds.RasterXSize
        rows = ds.RasterYSize

        tree = self._getMerkleTree()

        # ADDING metadata
        self._addMetadataToTree(self._robust_metadata(ds.GetMetadata()).items(), tree)
        self._addMetadataToTree(self._robust_metadata(band.GetMetadata()).items(), tree)

        for y in range(rows):
            row = band.ReadAsArray(0, y, cols, 1)[0]
            # mask nodata
            if nodata is not None:
                row = row[row != nodata]

            row = np.abs(np.round(row, decimals=self._precision))
            packed = row.astype(np.float32).tobytes()
            tree.append_entry(packed)

        root = tree.get_state()
        band = None
        ds = None
        return root.hex()
