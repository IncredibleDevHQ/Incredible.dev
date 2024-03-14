use log::debug;
use petgraph::graph::NodeIndex;
use tracing::field::debug;

use crate::graph::scope_graph::ScopeGraph;
use crate::graph::symbol_ops;
use crate::search::code_search::{ContentDocument, ExtractedContent, ExtractionConfig};
use crate::utilities::util::{adjust_byte_positions, get_line_number};

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
    pub fn expand_scope(
        &self,
        path: &String,
        start_byte: usize,
        end_byte: usize,
        source_document: &ContentDocument,
        line_end_indices: &Vec<usize>,
        config: &ExtractionConfig,
    ) -> ExtractedContent {
        debug!(
            "Looking for scope between byte range {} and {}",
            start_byte, end_byte
        );
        // Attempt to find a node within the scope graph that spans the given byte range.
        let node_idx = self.smallest_encompassing_node(start_byte, end_byte);
        //self.print_graph(5);
        let mut new_start = start_byte;
        let mut new_end = end_byte;

        if let Some(idx) = node_idx {
            // Node found: extract using the node's range.
            let node = &self.graph[self.value_of_definition(idx).unwrap_or(idx)];
            let range = node.range();
            debug!("Range retruned by post value of defintion: {:?}", range);
            // Adjust the starting byte to the beginning of the line.
            new_start = range.start.byte - range.start.column;

            // Determine the end byte based on the line end index or the node's range.
            new_end = line_end_indices
                .get(range.end.line)
                .map_or(range.end.byte, |&l| l as usize);

            // Check if the extracted content meets the minimum line requirement.
            let starting_line = get_line_number(new_start, line_end_indices);
            let ending_line = get_line_number(new_end, line_end_indices);
            let total_lines = ending_line - starting_line;

            if total_lines < config.min_lines_to_return {
                // Expand the scope if the content is less than the minimum line count.
                new_end = std::cmp::min(
                    new_end + config.code_byte_expansion_range,
                    source_document.content.len(),
                );
            } else if let Some(limit) = config.max_lines_limit {
                // Limit the content to the maximum line count if specified.
                if total_lines > limit {
                    new_end = line_end_indices
                        .get(starting_line + limit)
                        .map_or(new_end, |&l| l as usize);
                }
            }
        } else {
            // No node found: expand the range based on the configuration.
            debug!("Node not found");
            new_start = if start_byte > config.code_byte_expansion_range {
                start_byte - config.code_byte_expansion_range
            } else {
                0
            };

            new_end = std::cmp::min(
                end_byte + config.code_byte_expansion_range,
                source_document.content.len(),
            );
            (new_start, new_end) = adjust_byte_positions(new_start, new_end, line_end_indices);
        }

        // Recalculate line numbers after adjustment.
        let starting_line = get_line_number(new_start, line_end_indices);
        let ending_line = get_line_number(new_end, line_end_indices);
        debug!("Final byte range: {} to {}", new_start, new_end);
        debug!(
            "Start line: {}, End line: {} after adjusting in file {}",
            starting_line, ending_line, path
        );
        // Extract the content within the new byte range.
        let content = source_document.content[new_start..new_end].to_string();
        // get scope map for the final node, call get_scope_map node_idx is not None, otherwise set scope Map to None
        let scope_map = if let Some(idx) = node_idx {
            let hierarchy = self.get_scope_map(idx, &source_document.content, line_end_indices);
            debug!("Scope map for final node: {:?}", hierarchy);
            Some(hierarchy)
        } else {
            None
        };
        // Construct and return the extracted content with its metadata.
        ExtractedContent {
            path: path.clone(),
            content,
            start_byte: new_start,
            end_byte: new_end,
            start_line: starting_line,
            end_line: ending_line,
            scope_map: scope_map,
        }
    }

    /// Gets a single line of code based on the node's range within the file content.
    ///
    /// # Arguments
    /// * `node` - A NodeIndex identifying the specific node in the graph.
    /// * `file_content` - The entire content of the file as a string.
    /// * `line_end_indices` - A vector holding the byte indices of line endings in the file content.
    ///
    /// # Returns
    /// A tuple containing the extracted line of code as a string and the 1-based line number.
    fn get_code_line(
        &self,
        node: NodeIndex,
        file_content: &str,
        line_end_indices: &Vec<usize>,
    ) -> (String, usize) {
        // Fetch the range of the node within the file content.
        let range = self.graph[node].range();

        // Calculate the start index of the line by adjusting the range start with the column number.
        let line_start_index = range.start.byte - range.start.column;

        // Determine the end index for the line, using line end indices or the node's range end.
        let line_end_index = line_end_indices
            .get(range.start.line)
            .map_or(range.end.byte, |&l| l as usize);

        // Extract the line of code from the file content based on calculated indices.
        let line = &file_content[line_start_index..line_end_index];

        // Return the extracted line and the 1-based line number.
        (line.to_string(), range.start.line + 1)
    }

    /// Constructs a string representation of the hierarchical code structure starting from a given node.
    ///
    /// # Arguments
    /// * `start` - The starting NodeIndex from which to begin the extraction.
    /// * `file_content` - The entire content of the file as a string.
    /// * `line_end_indices` - A vector holding the byte indices of line endings in the file content.
    ///
    /// # Returns
    /// A string representing the nested code structure, annotated with line numbers and indentation.
    pub fn get_scope_map(
        &self,
        start: NodeIndex,
        file_content: &str,
        line_end_indices: &Vec<usize>,
    ) -> String {
        // Initialize with the starting node and prepare for traversal.
        let mut current_node = start;
        let mut code_blocks = Vec::new();
        let mut depth = 0; // Tracks the depth of nesting for indentation.

        // Traverse up the hierarchy until a top-level node is reached.
        while !self.is_top_level(current_node) {
            // Extract the line of code and its line number for the current node.
            let (line, line_number) =
                self.get_code_line(current_node, file_content, line_end_indices);
            // Prepare indentation based on the current depth.
            let indent = "    ".repeat(depth);

            // Insert ellipses to indicate skipped lines for non-consecutive code blocks.
            if let Some(last_line_number) = code_blocks
                .last()
                .and_then(|last: &String| last.split('>').next().unwrap().split_whitespace().last())
                .map(|num| num.parse::<usize>().ok())
                .flatten()
            {
                if last_line_number + 1 < line_number {
                    code_blocks.push(format!("{}..", indent));
                }
            }

            // Add the extracted line of code with proper indentation and line number annotation.
            code_blocks.push(format!("{}<Line number {}> {}", indent, line_number, line));

            // Move to the parent scope and increase depth, if possible.
            if let Some(parent) = self.parent_scope(current_node) {
                current_node = parent;
                depth += 1;
            } else {
                // Exit the loop if no parent is found, indicating the top level has been reached.
                break;
            }
        }

        // Add the line for the root scope node, without leading ellipses.
        let (root_line, root_line_number) =
            self.get_code_line(current_node, file_content, line_end_indices);
        code_blocks.push(format!(
            "<Root Scope Line number {}> {}",
            root_line_number, root_line
        ));

        // Since the traversal was bottom-up, reverse the blocks to present them top-down.
        code_blocks.reverse();
        // Join the code blocks into a single string, separated by new lines.
        code_blocks.join("\n")
    }
}
