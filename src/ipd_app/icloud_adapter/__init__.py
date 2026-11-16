"""iCloud access layer: the only package that knows how iCloud works."""

from .client import ICloudClient, ProgressCallback
from .errors import (
    AdvancedDataProtectionError,
    BadCredentialsError,
    BadTwoFactorCodeError,
    DownloadCancelled,
    ICloudError,
    LibraryNotReadyError,
    LinkExpiredError,
    NetworkError,
    SecurityKeyRequiredError,
    ServiceUnavailableError,
    SessionExpiredError,
    WebAccessDisabledError,
)
from .models import (
    Album,
    Asset,
    AssetFilter,
    AssetVersion,
    LoginResult,
    LoginStatus,
    MediaType,
    TrustedPhone,
    VersionKind,
)

__all__ = [
    "AdvancedDataProtectionError",
    "Album",
    "Asset",
    "AssetFilter",
    "AssetVersion",
    "BadCredentialsError",
    "BadTwoFactorCodeError",
    "DownloadCancelled",
    "ICloudClient",
    "ICloudError",
    "LibraryNotReadyError",
    "LinkExpiredError",
    "LoginResult",
    "LoginStatus",
    "MediaType",
    "NetworkError",
    "ProgressCallback",
    "SecurityKeyRequiredError",
    "ServiceUnavailableError",
    "SessionExpiredError",
    "TrustedPhone",
    "VersionKind",
    "WebAccessDisabledError",
]
