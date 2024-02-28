use std::io::{self, ErrorKind};

/// Extracts a specific range of lines from the provided text using line indices.
///
/// # Arguments
/// * `text` - The entire text from which a portion is to be extracted.
/// * `indices` - An array of byte indices marking the end of each line in the text.
/// * `start_line` - An optional 1-based index specifying the starting line to extract.
/// * `end_line` - An optional 1-based index specifying the ending line to extract.
///
/// # Returns
/// * A slice of the original text representing the specified line range.
/// * An IO error if the line numbers are out of bounds or invalid.
///
/// # Errors
/// * Returns an error if the start or end line is out of the valid range.
/// * Returns an error if the start line is greater than the end line.
pub fn pluck_code_by_lines<'a>(
    text: &'a str,
    indices: &Vec<usize>,
    start_line: Option<usize>,
    end_line: Option<usize>,
) -> Result<&'a str, io::Error> {
    // Determine the starting character index based on the start line.
    let char_start = match start_line {
        // If the start line is the first line, start from the beginning.
        Some(1) => 0,
        // If the start line is greater than one, calculate the start index from the indices array.
        Some(line_start) if line_start > 1 => {
            indices
                .get(line_start - 2) // Adjust for zero-based indexing and get the previous line's end.
                .ok_or_else(|| io::Error::new(ErrorKind::InvalidInput, "Invalid starting line number, cannot be greater than total lines of code"))?
                + 1 // Move to the character right after the line end.
        }
        // Default to the start of the text if no valid start is provided.
        Some(_) | None => 0,
    } as usize;

    // Determine the ending character index based on the end line.
    let line_end = match end_line {
        // Calculate the index if a valid end line is provided.
        Some(line_end) if line_end > 0 => line_end - 1,
        // Use the last line if no end line is specified.
        None => indices.len(),
        // Return an error if the end line is invalid.
        Some(_) => return Err(io::Error::new(ErrorKind::InvalidInput, "Start and end line cannot be negative")),
    };

    let char_end = if line_end < indices.len() {
        // Get the character index for the end of the specified range.
        indices[line_end] as usize
    } else {
        // Return an error if the end line is beyond the available lines.
        return Err(io::Error::new(ErrorKind::InvalidInput, "End line cannot be greater than the total number of lines"));
    };

    // Check for logical consistency: start should not be after end.
    if char_start > char_end {
        return Err(io::Error::new(ErrorKind::InvalidInput, "Start line cannot be greater than end line"));
    }

    // Return the specified substring, which is a range of lines.
    Ok(&text[char_start..=char_end])
}

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
