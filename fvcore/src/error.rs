//! Stable errors returned by the public Core API.

use serde::Serialize;
use std::fmt;
use thiserror::Error;

/// Machine-readable error categories exposed by every adapter.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    /// A caller supplied invalid input.
    InvalidInput,
    /// Configuration is invalid.
    InvalidConfig,
    /// A requested resource is already owned by another process.
    AlreadyRunning,
    /// The Core is not ready to accept the request.
    NotReady,
    /// A bounded queue cannot accept more work.
    Overloaded,
    /// The operation exceeded its deadline.
    DeadlineExceeded,
    /// The operation was cancelled.
    Cancelled,
    /// An input/output operation failed.
    Io,
    /// A configuration or control payload could not be parsed.
    Parse,
    /// An internal invariant failed without exposing sensitive details.
    Internal,
    /// The requested operation does not exist.
    OperationNotFound,
    /// The requested operation has already reached a terminal state.
    OperationFinished,
    /// The requested Provider profile does not exist.
    ProfileNotFound,
    /// The requested Provider resource does not exist.
    ResourceNotFound,
    /// Provider authentication is required or invalid.
    AuthenticationRequired,
    /// Provider denied access.
    AccessDenied,
    /// Provider rate limit was reached.
    RateLimited,
    /// Provider returned a response that violated the expected protocol.
    UnexpectedResponse,
    /// Received resource bytes failed declared length or checksum verification.
    IntegrityMismatch,
    /// A response exceeded the configured byte limit.
    ResponseTooLarge,
    /// A redirect target is not allowed for the Provider profile.
    RedirectDenied,
    /// Network transport failed before a valid response was received.
    Network,
}

impl ErrorCode {
    /// Returns the stable wire representation of this code.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidInput => "invalid_input",
            Self::InvalidConfig => "invalid_config",
            Self::AlreadyRunning => "already_running",
            Self::NotReady => "not_ready",
            Self::Overloaded => "overloaded",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::Cancelled => "cancelled",
            Self::Io => "io",
            Self::Parse => "parse",
            Self::Internal => "internal",
            Self::OperationNotFound => "operation_not_found",
            Self::OperationFinished => "operation_finished",
            Self::ProfileNotFound => "profile_not_found",
            Self::ResourceNotFound => "resource_not_found",
            Self::AuthenticationRequired => "authentication_required",
            Self::AccessDenied => "access_denied",
            Self::RateLimited => "rate_limited",
            Self::UnexpectedResponse => "unexpected_response",
            Self::IntegrityMismatch => "integrity_mismatch",
            Self::ResponseTooLarge => "response_too_large",
            Self::RedirectDenied => "redirect_denied",
            Self::Network => "network",
        }
    }
}

impl fmt::Display for ErrorCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

/// Public error with a stable code and a safe human-readable message.
#[derive(Clone, Debug, Error)]
#[error("{code}: {message}")]
pub struct CoreError {
    code: ErrorCode,
    message: String,
    retryable: bool,
}

impl CoreError {
    /// Constructs an error without retaining an unsafe source payload.
    #[must_use]
    pub fn new(code: ErrorCode, message: impl Into<String>, retryable: bool) -> Self {
        Self {
            code,
            message: message.into(),
            retryable,
        }
    }

    /// Returns the stable error category.
    #[must_use]
    pub const fn code(&self) -> ErrorCode {
        self.code
    }

    /// Returns a message safe to expose through CLI and HTTP adapters.
    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }

    /// Reports whether retrying without changing the request can succeed.
    #[must_use]
    pub const fn retryable(&self) -> bool {
        self.retryable
    }
}
