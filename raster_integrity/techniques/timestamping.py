"""
timestamping.py
===============
RFC 3161 Trusted Timestamping.

RFC 3161 is an internet standard for trusted timestamping. A
Timestamp Authority (TSA) cryptographically certifies that a given
hash value existed at a specific point in time. This provides:

    - Integrity verification: the data has not been modified since the timestamp
    - Non-repudiation: the time has been confirmed by an independent party
    - Legal evidentiary value: relevant for liability and archiving

Difference from HMAC:
    HMAC:         shared key between two parties → internal use
    Timestamping: independent third party → external proof, legally enforceable

Use at Hydrographic Offices:
    - Long-term archiving of bathymetric datasets
    - Legal proof of the state of a dataset at a specific point in time
    - Demonstrating when a survey was completed

Usage:
    # Compute timestamp (online via FreeTSA)
    openssl ts -reply -in file.tsr -text
    openssl ts -verify -in file.tsr -data file.txt -CAfile tsa_cert/cacert.pem

    # Verify a timestamp
    python timestamping.py --verify dataset.tif --timestamp dataset.tif.tsr

"""

from rfc3161_client import (
    TimestampRequestBuilder,
    decode_timestamp_response,
    VerifierBuilder,
    VerificationError,
)
import secrets
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes
import certifi
import os
import subprocess
from pathlib import Path
import urllib.request

TSA_EINDPUNTEN = {
    "freetsa": "https://freetsa.org/tsr",
    "digicert": "https://timestamp.digicert.com",
    "globalsign": "http://timestamp.globalsign.com/tsa/r45standard",
}
CACERT_URL = "https://freetsa.org/files/cacert.pem"


class Timestamping:

    def __init__(self, **kwargs):
        """
        Parameters
        ----------
        file : str or Path
            File used for timestamping
        """
        if "file" not in kwargs:
            raise TypeError("Missing required keyword argument: 'file'")

        self._file = Path(kwargs["file"])
        if not self._file.is_file():
            raise FileNotFoundError(f"Timestamping file not found: {self._file}")

    def label(self):
        return f"timestamping"

    def house_holding(self, url="output.xyz"):
        path = f"{url}.tsr"
        if os.path.exists(path):
            os.remove(path)

    def verify(self, url="output.xyz", integrity=""):
        """
        Clones this functionality
        openssl ts -verify -in file.tsr -data file.txt -CAfile tsa_cert/cacert.pem
        """
        ca_path = "data/tsa_cert/cacert.pem"
        self._ensure_file(ca_path)
        data_path = self._file
        try:
            with open(url, "rb") as f:
                tsr_bytes = f.read()

            tsr_object = decode_timestamp_response(tsr_bytes)

            with open(data_path, "rb") as f:
                message_data = f.read()

            with open(ca_path, "rb") as f:
                ca_certs = x509.load_pem_x509_certificates(f.read())

            builder = VerifierBuilder()
            for cert in ca_certs:
                builder.add_root_certificate(cert)

            verifier = builder.build()

            verifier.verify_message(tsr_object, message_data)

            print(" Verification: OK")
            return True

        except VerificationError as ve:
            print(f" Verification FAILED: Cryptografische fout of mismatch: {ve}")
            return False
        except Exception as e:
            print(f" Fout bij het uitvoeren van de verificatie: {e}")
            return False

    def create_integrity(self, url="output.xyz"):
        tsa_name = "freetsa"
        tsa_url = TSA_EINDPUNTEN.get(tsa_name)

        with open(self._file, "rb") as f:
            message = f.read()

        # Verzoek bouwen
        request = TimestampRequestBuilder().data(message).nonce().build()
        with open(f"{url}.tsq", "wb") as f:
            f.write(request.as_bytes())
        # print(request.nonce)
        # Sturen naar TSA
        response = requests.post(
            tsa_url,
            data=request.as_bytes(),
            headers={"Content-Type": "application/timestamp-query"},
        )
        timestamp_response = decode_timestamp_response(response.content)
        tsr = timestamp_response.as_bytes()
        with open(f"{url}.tsr", "wb") as f:
            f.write(tsr)

        return f"{url}.tsr"

    def _ensure_file(self, path, url=CACERT_URL):
        """Download `url` to `path` if the file does not exist yet."""
        if os.path.exists(path):
            return path

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        tmp_path = f"{path}.part"
        try:
            with urllib.request.urlopen(url, timeout=30) as response, open(
                tmp_path, "wb"
            ) as out:
                out.write(response.read())
            os.replace(
                tmp_path, path
            )  # atomair: nooit een half bestand onder de echte naam
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        return path
