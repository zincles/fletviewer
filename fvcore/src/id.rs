//! Strongly typed identifiers used by Core snapshots and commands.

use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;
use uuid::Uuid;

/// Identifies one isolated Core Runtime instance.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Deserialize, Serialize)]
#[serde(transparent)]
pub struct RuntimeId(Uuid);

impl RuntimeId {
    /// Creates a time-ordered UUID v7 Runtime identifier.
    #[must_use]
    pub fn new() -> Self {
        Self(Uuid::now_v7())
    }
}

impl Default for RuntimeId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for RuntimeId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Identifies one immutable operation lifecycle.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Deserialize, Serialize)]
#[serde(transparent)]
pub struct OperationId(Uuid);

impl OperationId {
    /// Creates a time-ordered UUID v7 Operation identifier.
    #[must_use]
    pub fn new() -> Self {
        Self(Uuid::now_v7())
    }
}

impl Default for OperationId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for OperationId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for OperationId {
    type Err = uuid::Error;

    fn from_str(input: &str) -> Result<Self, Self::Err> {
        Uuid::parse_str(input).map(Self)
    }
}
