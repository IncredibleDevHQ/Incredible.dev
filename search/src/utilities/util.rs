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
