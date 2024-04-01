/// Adjusts the byte positions to align with the start and end of lines in a document.
///
/// This function adjusts the provided byte positions to ensure that the text extracted
/// from these positions does not start or end in the middle of a line. It aligns the
/// start position to the beginning of the first full line within the range and the end
/// position to the end of the last full line within the range.
///
/// # Parameters
/// - `initial_start_byte`: The initial start byte position that might be in the middle of a line.
/// - `initial_end_byte`: The initial end byte position that might be in the middle of a line.
/// - `line_end_indices`: A reference to a vector containing the byte indices of the end of each line.
///
/// # Returns
/// A tuple containing the adjusted start and end byte positions.
pub fn adjust_byte_positions(
    initial_start_byte: usize,
    initial_end_byte: usize,
    line_end_indices: &Vec<usize>,
) -> (usize, usize) {
    // Determine the line number for the initial end position.
    let ending_line = get_line_number(initial_end_byte, &line_end_indices);
    // Determine the line number for the initial start position.
    let starting_line = get_line_number(initial_start_byte, &line_end_indices);

    // Use the end of the previous line to adjust the start position, ensuring it starts at the beginning of a line.
    let mut previous_line = starting_line;
    if previous_line > 0 {
        previous_line -= 1; // Move to the end of the previous line to find the start of the next line.
    }

    // Adjust the start byte to the first character of the starting line by using the end of the previous line.
    let adjusted_start = line_end_indices
        .get(previous_line) // Get the byte index for the end of the previous line.
        .map(|l| *l as usize) // Dereference and cast to usize.
        .unwrap_or(initial_start_byte) // If the line index is not found, default to `initial_start_byte`.
        + 1; // Move to the first character of the next line.

    // Adjust the end byte to the last character of the ending line.
    let adjusted_end = line_end_indices
        .get(ending_line) // Get the byte index for the end of the ending line.
        .map(|l: &usize| *l as usize) // Dereference and cast to usize.
        .unwrap_or(initial_end_byte); // If the line index is not found, default to `initial_end_byte`.

    // Return the adjusted start and end byte positions.
    (adjusted_start, adjusted_end)
}

/// Determines the line number in a document based on a given byte position.
///
/// This function iterates through an array of byte indices that mark the end of each line
/// in the document. It finds the line number where the given byte position falls. This is
/// useful for mapping byte positions back to human-readable line numbers in a text document.
///
/// # Parameters
/// - `byte`: The byte position in the document for which the line number is being determined.
/// - `line_end_indices`: A slice containing the byte positions that mark the end of each line.
///
/// # Returns
/// The line number (0-indexed) where the given byte position falls within the document.
///
/// # Notes
/// - If `byte` is 0, the function assumes it's the beginning of the document and returns 0.
/// - The function returns 0 for any byte position that does not fall within the ranges
///   defined in `line_end_indices`, which can indicate either an error in input or that
///   the byte is beyond the last known line end.
pub fn get_line_number(byte: usize, line_end_indices: &[usize]) -> usize {
    // Directly return 0 for the beginning of the document.
    if byte == 0 {
        return 0;
    }

    // Iterate over the line end indices to find the first one that is greater than or equal to the byte position.
    // The position of this line end index in the array gives the line number.
    let line = line_end_indices
        .iter()
        .position(|&line_end_byte| line_end_byte >= byte)
        // If no such line end byte is found, default to 0, indicating an unexpected input or byte beyond the document.
        .unwrap_or(0);
    // debug print the the byte position for the obtained line number from line_end_indices
    log::debug!(
        "Reverse byte lookup: {}, line number: {}",
        line_end_indices[line], line
    );

    return line;
}

#[cfg(test)]
mod tests {
    use super::*;

    // A helper function to simulate line end indices for a hypothetical document.
    fn setup_line_end_indices() -> Vec<usize> {
        vec![10, 20, 30, 40, 50, 60, 70, 80, 90, 100] // Each number represents the end of a line in the document.
    }

    #[test]
    fn test_adjust_byte_positions() {
        let line_end_indices = setup_line_end_indices();

        // Case 1: Start and end within the same line.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(15, 25, &line_end_indices);
        assert_eq!(adjusted_start, 11);
        assert_eq!(adjusted_end, 20);

        // Case 2: Start and end at exact line boundaries.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(10, 30, &line_end_indices);
        assert_eq!(adjusted_start, 11);
        assert_eq!(adjusted_end, 30);

        // Case 3: Start at the beginning and end at the end of the document.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(0, 100, &line_end_indices);
        assert_eq!(adjusted_start, 1);
        assert_eq!(adjusted_end, 100);

        // Case 4: Start and end at the beginning of lines.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(11, 31, &line_end_indices);
        assert_eq!(adjusted_start, 11);
        assert_eq!(adjusted_end, 30); // Adjusted because end should fall at the end of the previous line.

        // Case 5: Start and end at the end of lines.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(20, 40, &line_end_indices);
        assert_eq!(adjusted_start, 21); // Adjusted to the start of the next line.
        assert_eq!(adjusted_end, 40);

        // Case 6: Edge case - Start and end at the very end of the document.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(95, 100, &line_end_indices);
        assert_eq!(adjusted_start, 91); // Adjusted to the start of the line containing position 95.
        assert_eq!(adjusted_end, 100); // Remains as the end of the document.

        // Case 7: Edge case - Start is at the first byte of the document.
        let (adjusted_start, adjusted_end) = adjust_byte_positions(0, 15, &line_end_indices);
        assert_eq!(adjusted_start, 1); // Adjusted to the first character of the document (after line end index at 0).
        assert_eq!(adjusted_end, 10); // Adjusted to the end of the line containing position 15.
    }

    #[test]
    fn test_get_line_number() {
        let line_end_indices = setup_line_end_indices();

        // Case 1: Byte is zero (beginning of the document).
        assert_eq!(get_line_number(0, &line_end_indices), 0);

        // Case 2: Byte is within the first line.
        assert_eq!(get_line_number(5, &line_end_indices), 0);

        // Case 3: Byte is at the end of the first line.
        assert_eq!(get_line_number(10, &line_end_indices), 0);

        // Case 4: Byte is at the beginning of the second line.
        assert_eq!(get_line_number(11, &line_end_indices), 1);

        // Case 5: Byte is within the second line.
        assert_eq!(get_line_number(15, &line_end_indices), 1);

        // Case 6: Byte is at the end of the last line (line 4, index 3 considering zero-indexed).
        assert_eq!(get_line_number(50, &line_end_indices), 4);

        // Case 7: Byte is beyond the last line.
        assert_eq!(get_line_number(55, &line_end_indices), 0); // Returns 0 since it's beyond the known lines.

        // Case 8: Checking with a byte position that's right at a line ending.
        // Should return the line on which the byte is located (not the next line).
        assert_eq!(get_line_number(20, &line_end_indices), 1);

        // Case 9: Byte is at the very end of the document, simulating the behavior when the byte is right at the last line ending.
        assert_eq!(get_line_number(50, &line_end_indices), 4);
    }
}