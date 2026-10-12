"""File Upload Service.

An S3-style upload service storing files on local disk with
content-addressable (BLAKE2b) names, MIME sniffing from bytes, and
HMAC-signed download URLs.
"""

__version__ = "0.1.0"