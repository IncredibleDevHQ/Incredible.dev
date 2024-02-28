use crate::graph::scope_graph::ScopeGraph;
use crate::search::code_search::{ContentDocument, ExtractedContent, ExtractionConfig};
use crate::utilities::util::{adjust_byte_positions, get_line_number};
use crate::graph::symbol_ops;

impl ScopeGraph {
    /// Expands the scope around a given byte range to extract relevant content,
    /// adjusting according to the scope graph and configuration settings.
    ///
    /// # Parameters
    /// - `path`: Reference to the string representing the path of the source document.
    /// - `start_byte`: The starting byte index for the content extraction.
    /// - `end_byte`: The ending byte index for the content extraction.
    /// - `source_document`: Reference to the content document from which to extract content.
    /// - `line_end_indices`: Vector of byte indices where each line in the document ends.
    /// - `config`: Configuration settings that guide the scope expansion.
    ///
    /// # Returns
    /// - `ExtractedContent`: The extracted content including its metadata like start and end positions.
    fn expand_scope(
        &self,
        path: &String,
        start_byte: usize,
        end_byte: usize,
        source_document: &ContentDocument,
        line_end_indices: &Vec<usize>,
        config: &ExtractionConfig,
    ) -> ExtractedContent {
        // Attempt to find a node within the scope graph that spans the given byte range.
        let node_idx = self.node_by_range(start_byte, end_byte);

        let mut new_start = start_byte;
        let mut new_end = end_byte;

        if let Some(idx) = node_idx {
            // Node found: extract using the node's range.
            let node = &self.graph[self.value_of_definition(idx).unwrap_or(idx)];
            let range = node.range();

            // Adjust the starting byte to the beginning of the line.
            new_start = range.start.byte - range.start.column;

            // Determine the end byte based on the line end index or the node's range.
            new_end = line_end_indices.get(range.end.line).map_or(range.end.byte, |&l| l as usize);

            // Check if the extracted content meets the minimum line requirement.
            let starting_line = get_line_number(new_start, line_end_indices);
            let ending_line = get_line_number(new_end, line_end_indices);
            let total_lines = ending_line - starting_line;

            if total_lines < config.min_lines_to_return {
                // Expand the scope if the content is less than the minimum line count.
                new_end = std::cmp::min(new_end + config.code_byte_expansion_range, source_document.content.len());
            } else if let Some(limit) = config.max_lines_limit {
                // Limit the content to the maximum line count if specified.
                if total_lines > limit {
                    new_end = line_end_indices.get(starting_line + limit).map_or(new_end, |&l| l as usize);
                }
            }
        } else {
            // No node found: expand the range based on the configuration.
            new_start = if start_byte > config.code_byte_expansion_range {
                start_byte - config.code_byte_expansion_range
            } else {
                0
            };

            new_end = std::cmp::min(end_byte + config.code_byte_expansion_range, source_document.content.len());
            adjust_byte_positions(new_start, new_end, line_end_indices);
        }

        // Recalculate line numbers after adjustment.
        let starting_line = get_line_number(new_start, line_end_indices);
        let ending_line = get_line_number(new_end, line_end_indices);

        // Extract the content within the new byte range.
        let content = source_document.content[new_start..new_end].to_string();

        // Construct and return the extracted content with its metadata.
        ExtractedContent {
            path: path.clone(),
            content,
            start_byte: new_start,
            end_byte: new_end,
            start_line: starting_line,
            end_line: ending_line,
        }
    }
}

