//! Pure Rust application core for FletViewer and future frontends.
//!
//! The crate intentionally starts with a small surface. Provider, storage,
//! task, and resource contracts will be added behind stable Rust APIs before
//! server, C ABI, or frontend adapters are introduced.

#![forbid(unsafe_code)]
#![warn(missing_docs)]

/// Crate version compiled into the current artifact.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Returns the semantic version of this `fvcore` build.
#[must_use]
pub const fn version() -> &'static str {
    VERSION
}

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_package_metadata() {
        assert_eq!(super::version(), env!("CARGO_PKG_VERSION"));
    }
}
