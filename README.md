# raster_integrity


[![image](https://img.shields.io/pypi/v/raster_integrity.svg)](https://pypi.python.org/pypi/raster_integrity)
[![image](https://img.shields.io/conda/vn/conda-forge/raster_integrity.svg)](https://anaconda.org/conda-forge/raster_integrity)

[![image](https://pyup.io/repos/github/wdedulle/raster_integrity/shield.svg)](https://pyup.io/repos/github/wdedulle/raster_integrity)


**Technical methods for checking the integrity of raster data**


-   Free software: MIT License
-   Documentation: https://wdedulle.github.io/raster_integrity


## Features

-   Setting up metadata for raster files: it includes common and custom raster information.
```shell
python .\raster_integrity\setup.py -f .\data\classified.xyz -m "used_for"="classification for AI"
```

-   Creating integrity hash
```shell
python .\raster_integrity\integrity.py -i .\data\classified.jpg -t me
8eb3bdddc021b045622f9811ff925d132ad6274f0bba6546dcbf6014dac19bdf
```
-   Archive all artefacts with its integrity hash
```shell
python .\raster_integrity\integrity.py -i .\data\classified.jpg -t ba -a root_hash=8eb3bdddc021b045622f9811ff925d132ad6274f0bba6546dcbf6014dac19bdf
.\data\classified_bagit
```
-   Seal the tagmanifest with timestamping
```shell
python .\raster_integrity\integrity.py -i .\data\classified_bagit\tagmanifest-sha256.txt -t ts -a tsr_name=.\data\tagmanifest_cassified_jpg
.\data\tagmanifest_cassified_jpg.tsr
```

-   Verification - To Be
```shell
python .\raster_integrity\verify.py -a file=.\data\classified_bagit\tagmanifest-sha256.txt -t ts -s .\data\classified.jpg.tsr
python .\raster_integrity\verify.py -a root_hash=8eb3bdddc021b045622f9811ff925d132ad6274f0bba6546dcbf6014dac19bdf -t me -s .\data\classified.jpg
```

## Required package
GDAL: Geospatial Data Abstraction Library version 3.13.3
### Installation for Python 3.15
Wheel packages can be found at https://github.com/cgohlke/geospatial-wheels/releases

This a specific GDAL version 3.13.3 installation for Windows AMD64 with Python version 3.15.*
```
pip install https://github.com/cgohlke/geospatial-wheels/releases/download/v2026.8.20/gdal-3.13.3-cp315-cp315-win_amd64.whl
```