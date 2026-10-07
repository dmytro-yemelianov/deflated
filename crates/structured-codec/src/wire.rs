use alloc::vec::Vec;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    BadMagic,
    UnsupportedVersion,
    BadFlags,
    BadChunkCount,
    InvalidLength,
    UnexpectedEof,
    NoncanonicalVarint,
    IntegerOverflow,
    BadStorage,
    DeflateError,
    TrailingData,
    DuplicateDictionary,
    BadDictionaryId,
    BadOpcode,
    MissingNumericBase,
    UnusedSubstream,
    OutputLimit,
    ChecksumMismatch,
}

impl Error {
    pub fn category(self) -> &'static str {
        match self {
            Self::BadMagic => "badMagic",
            Self::UnsupportedVersion => "unsupportedVersion",
            Self::BadFlags => "badFlags",
            Self::BadChunkCount => "badChunkCount",
            Self::InvalidLength => "invalidLength",
            Self::UnexpectedEof => "unexpectedEof",
            Self::NoncanonicalVarint => "noncanonicalVarint",
            Self::IntegerOverflow => "integerOverflow",
            Self::BadStorage => "badStorage",
            Self::DeflateError => "deflateError",
            Self::TrailingData => "trailingData",
            Self::DuplicateDictionary => "duplicateDictionary",
            Self::BadDictionaryId => "badDictionaryId",
            Self::BadOpcode => "badOpcode",
            Self::MissingNumericBase => "missingNumericBase",
            Self::UnusedSubstream => "unusedSubstream",
            Self::OutputLimit => "outputLimit",
            Self::ChecksumMismatch => "checksumMismatch",
        }
    }
}

pub(crate) fn check(condition: bool, error: Error) -> Result<(), Error> {
    if condition { Ok(()) } else { Err(error) }
}

pub(crate) struct Cursor<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> Cursor<'a> {
    pub(crate) fn new(data: &'a [u8]) -> Self {
        Self { data, pos: 0 }
    }

    pub(crate) fn remaining(&self) -> usize {
        self.data.len() - self.pos
    }

    pub(crate) fn take(&mut self, n: usize) -> Result<&'a [u8], Error> {
        check(n <= self.remaining(), Error::UnexpectedEof)?;
        let start = self.pos;
        self.pos += n;
        Ok(&self.data[start..self.pos])
    }

    pub(crate) fn byte(&mut self) -> Result<u8, Error> {
        Ok(self.take(1)?[0])
    }

    pub(crate) fn u16(&mut self) -> Result<u16, Error> {
        Ok(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| Error::UnexpectedEof)?,
        ))
    }

    pub(crate) fn u32(&mut self) -> Result<u32, Error> {
        Ok(u32::from_le_bytes(
            self.take(4)?.try_into().map_err(|_| Error::UnexpectedEof)?,
        ))
    }

    pub(crate) fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| Error::UnexpectedEof)?,
        ))
    }

    pub(crate) fn varint(&mut self) -> Result<u64, Error> {
        let mut value = 0;
        for i in 0..10 {
            let byte = self.byte()?;
            let bits = byte & 127;
            check(i != 9 || (bits <= 1 && byte < 128), Error::IntegerOverflow)?;
            value |= u64::from(bits) << (7 * i);
            if byte < 128 {
                check(i == 0 || bits != 0, Error::NoncanonicalVarint)?;
                return Ok(value);
            }
        }
        Err(Error::IntegerOverflow)
    }
}

pub(crate) fn put_varint(mut value: u64, out: &mut Vec<u8>) {
    while value >= 128 {
        out.push((value as u8 & 127) | 128);
        value >>= 7;
    }
    out.push(value as u8);
}

pub(crate) fn varint_len(mut value: u64) -> usize {
    let mut length = 1;
    while value >= 128 {
        value >>= 7;
        length += 1;
    }
    length
}
