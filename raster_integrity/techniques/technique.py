import os


class Technique:
    def __init__(self, **kwargs):
        """
        Parameters
        ----------
        file : str
            Raster file for creating integrity
        """
        if "file" not in kwargs:
            raise TypeError("Missing required keyword argument: 'file'")

        self._file = kwargs["file"]
        if not os.path.exists(self._file):
            raise ValueError(f"File '{self._file}' does not exist")
