"""
archiving.py
===================
BagIt packaging for long-term archiving.

BagIt (RFC 8493) is a hierarchical file packaging format for the storage and
transfer of digital content. A "bag" is a directory containing the payload
files together with a manifest of checksums, so that the completeness and
integrity of the content can be verified at any time. This provides:

    - Completeness check: all files in the manifest are present in the bag
    - Integrity verification: checksums confirm that no file was altered
    - Self-describing packages: metadata travels with the data
    - Portability: plain files and text manifests, no special software required

Structure of a bag:
    bag/
    ├── bagit.txt              BagIt version and tag file encoding
    ├── bag-info.txt           descriptive metadata (source, date, contact, ...)
    ├── manifest-sha256.txt    checksums of all payload files
    ├── tagmanifest-sha256.txt checksums of the tag files
    └── data/                  the payload (e.g. the bathymetric datasets)

Difference from timestamping:
    BagIt:        checksums + metadata → proves what a package contains
    Timestamping: independent third party → proves when it existed
    The two are complementary: a bag manifest can be timestamped to prove
    both the content and the time of archiving.

Use at Hydrographic Offices:
    - Packaging bathymetric datasets (e.g. GeoTIFF) for long-term archiving
    - Detecting bit rot or accidental modification of archived surveys
    - Transferring datasets to other parties with verifiable integrity

Usage:
    # Create a bag from a directory
    bag = bagit.make_bag("survey_2024/", {"Source-Organization": "Flemish Hydrography"})

    # Validate an existing bag
    bag = bagit.Bag("survey_2024/")
    bag.validate()
"""

import bagit
import os
import shutil
from osgeo import gdal
from .technique import Technique

gdal.UseExceptions()


class BagItArchive(Technique):
    def label(self):
        return f"archive_bagit"

    def _house_holding(self):
        directory = self._get_directory(self._file)

        if os.path.exists(directory):
            shutil.rmtree(directory)
        os.makedirs(directory)

        filename = os.path.basename(self._file)
        shutil.copy(self._file, os.path.join(directory, filename))

        aux = f"{self._file}.aux.xml"
        if os.path.exists(aux):
            shutil.copy(aux, os.path.join(directory, f"{filename}.aux.xml"))

    def create_integrity(self, **kwargs):
        """
        Parameters
        ----------
        root_hash : str
            Integrity hash key for storing into bag, for validation on data/info content
        """
        if "root_hash" not in kwargs:
            raise TypeError("Missing required keyword argument: 'root_hash'")

        self._root_hash = kwargs["root_hash"]
        self._house_holding()
        bag = bagit.make_bag(
            self._get_directory(self._file),
            {
                "fingerprint": self._root_hash,
            },
        )
        return bag

    def _get_directory(self, file):
        root, _ = os.path.splitext(file)
        return f"{root}_bagit"

    def _create_directory(self, file):
        dir = self._get_directory(file)
        if not os.path.exists(dir):
            os.mkdir(dir)
        return dir
