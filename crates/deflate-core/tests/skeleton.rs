#[test]
fn error_variants_are_distinct_and_copy() {
    use deflate_core::Error;
    let a = Error::UnexpectedEof;
    let b = a; // Copy
    assert_eq!(a, b);
    assert_ne!(Error::UnexpectedEof, Error::InvalidBlockType);
}
