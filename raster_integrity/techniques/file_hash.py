"""
file_hash.py
============
Cryptographic file hashing for integrity verification.

A cryptographic hash function maps a file of arbitrary size to a fixed-length
digest (the "fingerprint" of the file). Any change to the file, however small,
results in a completely different digest. This provides:

    - Integrity verification: detect accidental corruption or modification
    - Change detection: compare a file against a previously stored digest
    - Deduplication: identical content yields an identical digest

The default algorithm is SHA-256 (SHA-2 family, specified in NIST FIPS 180-4).
Any algorithm supported by Python's hashlib can be selected instead.
Files are read in 64 KB chunks, so large datasets (e.g. GeoTIFF rasters or
point clouds) can be hashed without loading them into memory.

Difference from HMAC and timestamping:
    File hash:    digest of the content only -> proves the file is unchanged
                  relative to a known digest
    HMAC:         digest + shared secret key -> also proves who created it
    Timestamping: digest + independent third party -> proves when it existed
    A plain hash offers no authenticity: anyone can recompute it. It is
    therefore only trustworthy when the reference digest itself is stored
    or transmitted through a trusted channel (e.g. in a signed or
    timestamped manifest).

Used for:
    - Fixity checks on archived bathymetric datasets
    - Verifying that a dataset was transferred without corruption

Usage:
    hasher = FileHash(algorithm="sha256")

    # Create the digest of a file
    digest = hasher.create_integrity("dataset.tif")

    # Verify a file against a stored digest
    ok = hasher.verify("dataset.tif", integrity=digest)
"""

import os
import hashlib
from osgeo import gdal

gdal.UseExceptions()


class FileHash:
    def __init__(self, **kwargs):
        """
        Parameters
        ----------
        algorithm : str
            kind of algorithm to used for creating hash key
            standard: "sha256"
        """
        if "algorithm" in kwargs:
            self._algorithm = kwargs["algorithm"]
        else:
            self._algorithm = "sha256"

    def label(self):
        return "file_hash"

    def verify(self, url="output.xyz", integrity=""):
        return self.create_integrity(url) == integrity

    def house_holding(self, url="output.xyz"):
        path = f"{url}_hash"
        if os.path.exists(path):
            os.remove(path)

    def create_integrity(self, url="output.xyz"):
        hasher = hashlib.new(self._algorithm)
        with open(url, "rb") as f:
            while chunk := f.read(65536):  # 64KB chunks
                hasher.update(chunk)
        digest = hasher.hexdigest()
        return digest
