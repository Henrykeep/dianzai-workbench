//! Flash programming and management

pub mod manager;

pub use manager::{
    EraseResult, EraseType, FileFormat, FlashManager, ProgramResult, VerifyMismatch, VerifyResult,
};
