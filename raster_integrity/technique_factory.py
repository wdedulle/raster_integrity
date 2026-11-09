"""
technique_factory.py
=====================
Factory-implementation for creating of different types of
hashing- and validation techniques based on short codes.
"""

from enum import Enum
from techniques.file_hash import FileHash
from techniques.merkle_tree_hash import *
from techniques.archiving import *
from techniques.timestamping import *


class TechniqueType(Enum):
    FILE_HASH = "fh"
    MERKLE = "me"
    MERKLE_ROBUST = "mr"
    MERKLE_SQLITE = "ms"
    BAGIT_ARCHIVING = "ba"
    TIMESTAMPING = "ts"


class TechniqueFactory:
    _mapping = {
        TechniqueType.FILE_HASH: FileHash,
        TechniqueType.MERKLE: MerkleTreeInmemoryHash,
        TechniqueType.MERKLE_ROBUST: MerkleTreeInmemoryRobustHash,
        TechniqueType.MERKLE_SQLITE: MerkleTreeSqliteHash,
        TechniqueType.BAGIT_ARCHIVING: BagItArchive,
        TechniqueType.TIMESTAMPING: Timestamping,
    }

    @classmethod
    def create(self, code: str, **kwargs):
        try:
            hash_type = TechniqueType(code)
        except ValueError:
            raise ValueError(
                f"Unknown technique code '{code}'.\n"
                f"Available codes:\n{self.help_text()}"
            )

        return self._mapping[hash_type](kwargs)


class TechniqueFactory:
    _mapping = {
        TechniqueType.FILE_HASH: FileHash,
        TechniqueType.MERKLE: MerkleTreeInmemoryHash,
        TechniqueType.MERKLE_ROBUST: MerkleTreeInmemoryRobustHash,
        TechniqueType.MERKLE_SQLITE: MerkleTreeSqliteHash,
        TechniqueType.BAGIT_ARCHIVING: BagItArchive,
        TechniqueType.TIMESTAMPING: Timestamping,
    }

    @classmethod
    def create(cls, code: str, **kwargs):
        try:
            technique_type = TechniqueType(code)
        except ValueError:
            raise ValueError(
                f"Unknown technique code '{code}'.\n"
                f"Available codes:\n{cls.help_text()}"
            ) from None

        return cls._mapping[technique_type](**kwargs)

    @staticmethod
    def help_text():
        return (
            "Techniques and their extra arguments (use -a KEY=VALUE):\n"
            "\n"
            "  fh  File hashing (digest of the file bytes)\n"
            "        algorithm   hashlib algorithm            [default: sha256]\n"
            "\n"
            "  me  Merkle tree with hashing (in memory)\n"
            "        algorithm   hashlib algorithm            [default: sha256]\n"
            "\n"
            "  mr  Merkle tree with robust hashing\n"
            "        algorithm   hashlib algorithm            [default: sha256]\n"
            "        precision   decimals to round (int)      [default: 3]\n"
            "\n"
            "  ms  Merkle tree with hashing, stored in SQLite (<file>.db)\n"
            "        algorithm   hashlib algorithm            [default: sha256]\n"
            "\n"
            "  ba  RFC 8493 BagIt archiving\n"
            "        root_hash   fingerprint stored in the bag [required]\n"
            "\n"
            "  ts  RFC 3161 trusted timestamping\n"
            "        file        file used for timestamping    [required]\n"
        )
