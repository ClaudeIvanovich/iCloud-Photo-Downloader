"""Typed errors of the iCloud layer. The rest of the app never sees library exceptions."""

from __future__ import annotations

from .. import strings


class ICloudError(Exception):
    """Base error. `user_message` is Russian and safe to show; str() is for logs."""

    user_message = strings.ERR_ICLOUD_GENERIC
    transient = False

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or type(self).__name__)
        self.detail = detail
        if "{detail}" in self.user_message:
            self.user_message = self.user_message.format(detail=detail or type(self).__name__)


class BadCredentialsError(ICloudError):
    user_message = strings.ERR_BAD_CREDENTIALS


class BadTwoFactorCodeError(ICloudError):
    user_message = strings.ERR_BAD_2FA_CODE


class SessionExpiredError(ICloudError):
    user_message = strings.ERR_SESSION_EXPIRED


class AdvancedDataProtectionError(ICloudError):
    user_message = strings.ERR_ADP


class WebAccessDisabledError(ICloudError):
    user_message = strings.ERR_WEB_ACCESS


class SecurityKeyRequiredError(ICloudError):
    user_message = strings.ERR_SECURITY_KEY


class LibraryNotReadyError(ICloudError):
    user_message = strings.ERR_LIBRARY_NOT_READY


class NetworkError(ICloudError):
    """Connection dropped, timeout, DNS. Worth retrying."""

    user_message = strings.ERR_NETWORK
    transient = True


class ServiceUnavailableError(ICloudError):
    """HTTP 429 / 5xx or throttling. Worth retrying."""

    user_message = strings.ERR_UNAVAILABLE
    transient = True


class DownloadCancelled(Exception):
    """Raised from a progress callback to abort a download in flight."""
