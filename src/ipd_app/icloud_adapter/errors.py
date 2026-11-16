"""Typed errors of the iCloud layer. The rest of the app never sees library exceptions."""

from __future__ import annotations

from .. import strings


class ICloudError(Exception):
    """Base error. `user_message` is in the user's language and safe to show; str() is for logs."""

    message_key = "ERR_ICLOUD_GENERIC"
    transient = False

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or type(self).__name__)
        self.detail = detail
        # Looked up now, not at import: the language is chosen after this module loads.
        template = getattr(strings, self.message_key)
        self.user_message = template.format(detail=detail or type(self).__name__) if "{detail}" in template else template


class BadCredentialsError(ICloudError):
    message_key = "ERR_BAD_CREDENTIALS"


class BadTwoFactorCodeError(ICloudError):
    message_key = "ERR_BAD_2FA_CODE"


class SessionExpiredError(ICloudError):
    message_key = "ERR_SESSION_EXPIRED"


class AdvancedDataProtectionError(ICloudError):
    message_key = "ERR_ADP"


class WebAccessDisabledError(ICloudError):
    message_key = "ERR_WEB_ACCESS"


class SecurityKeyRequiredError(ICloudError):
    message_key = "ERR_SECURITY_KEY"


class LibraryNotReadyError(ICloudError):
    message_key = "ERR_LIBRARY_NOT_READY"


class NetworkError(ICloudError):
    """Connection dropped, timeout, DNS. Worth retrying."""

    message_key = "ERR_NETWORK"
    transient = True


class ServiceUnavailableError(ICloudError):
    """HTTP 429 / 5xx or throttling. Worth retrying."""

    message_key = "ERR_UNAVAILABLE"
    transient = True


class DownloadCancelled(Exception):
    """Raised from a progress callback to abort a download in flight."""
