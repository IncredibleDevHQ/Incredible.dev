use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
};

use compact_str::CompactString;
use smallvec::SmallVec;

/// Get all case permutations of a string.
///
/// This permutes each character by ASCII lowercase and uppercase variants. Characters which do not
/// have case variants remain unchanged.
pub fn case_permutations(s: &str) -> impl Iterator<Item = CompactString> {
    // This implements a bitmask-based algorithm. The purpose is not speed; rather, a bitmask is
    // a simple way to get all combinations of a set of flags without allocating, sorting, or doing
    // anything else that is fancy.
    //
    // For example, given a list of 4 characters, we can represent which one is uppercased with a
    // bitmask: `0011` means that the last two characters are uppercased. To make things simpler
    // for the algorithm, we can reverse the bitmask to get `1100`; this allows us to create a
    // *new* bitmask specific to that character by simply doing `(1 << character_index)`. To see
    // this clearer, we can use a real string and break down all the masks:
    //
    //  - Example string: "abCD"
    //  - uppercase_bitmask: 1100
    //
    //  - "a" @ index 0, bitmask: (1 << 0) = 0001
    //  - "b" @ index 1, bitmask: (1 << 1) = 0010
    //  - "C" @ index 1, bitmask: (1 << 2) = 0100   (uppercased)
    //  - "D" @ index 1, bitmask: (1 << 3) = 1000   (uppercased)
    //                                 ----------
    //  - OR all of the uppercased masks   = 1100   (the uppercase bitmask)
    //
    // Using this, we can iterate through all combinations of letter casings by simply incrementing
    // the mask number, resulting in `0000`, `0001`, `0010`, `0011`, `0100`, etc...
    //
    // The algorithm below uses this mask to create all permutations of casings.

    let chars = s
        .chars()
        .map(|c| c.to_ascii_lowercase())
        .collect::<SmallVec<[char; 3]>>();

    // Make sure not to overflow. The end condition is a mask with the highest bit set, and we use
    // `u32` masks.
    debug_assert!(chars.len() <= 31);

    let num_chars = chars.len();

    let mut mask = 0b000;
    let end_mask = 1 << num_chars;
    let non_ascii_mask = chars
        .iter()
        .enumerate()
        .filter_map(|(i, c)| {
            if *c == c.to_ascii_uppercase() {
                Some(i)
            } else {
                None
            }
        })
        .map(|i| 1 << i)
        .fold(0u32, |a, e| a | e);

    std::iter::from_fn(move || {
        // Skip over variants that try to uppercase non-ascii letters.
        while mask < end_mask && (mask & non_ascii_mask) != 0 {
            mask += 1;
        }

        if mask >= end_mask {
            return None;
        }

        let permutation = chars
            .iter()
            .enumerate()
            .map(|(i, c)| {
                if mask & (1 << i) != 0 {
                    c.to_ascii_uppercase()
                } else {
                    *c
                }
            })
            .collect::<CompactString>();

        mask += 1;

        Some(permutation)
    })
}
