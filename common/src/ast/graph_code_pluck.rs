use log::debug;
use petgraph::graph::NodeIndex;
use serde::{Deserialize, Serialize};

use crate::ast::utils::{adjust_byte_positions, get_line_number};

use super::{ast_graph::ScopeGraph, symbol::SymbolLocations, text_range::TextRange, CodeFileAST};

#[derive(Serialize, Deserialize, Default, Debug, Clone)]
pub struct ExtractedContent {
    pub path: String,
    pub content: String,
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub end_line: usize,
    pub scope_map: Option<String>,
}

#[derive(Default, Debug, Clone, Serialize)]
pub struct ExtractionConfig {
    pub code_byte_expansion_range: usize, // Number of bytes to expand from the start and end.
    pub min_lines_to_return: usize,       // Minimum number of lines the extraction should return.
    pub max_lines_limit: Option<usize>,   // Optional maximum number of lines to extract.
}

#[derive(Default, Debug, Clone, Serialize)]
pub struct ContentDocument {
    pub repo_name: String,
    pub repo_ref: String,
    pub relative_path: String,
    pub lang: Option<String>,
    pub line_end_indices: Vec<u8>,
    pub content: String,
    pub symbol_locations: Vec<u8>,
    pub symbols: String,
}

impl ContentDocument {
    pub fn fetch_line_indices(&self) -> Vec<usize> {
        let line_end_indices: Vec<usize> = self
            .line_end_indices
            .chunks(4)
            .filter_map(|chunk| {
                // Convert each 4-byte chunk to a u32.
                if chunk.len() == 4 {
                    let value =
                        u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]) as usize;
                    Some(value)
                } else {
                    None
                }
            })
            .collect();

        line_end_indices
    }
    pub fn symbol_locations(&self) -> anyhow::Result<SymbolLocations> {
        let symbol_locations = bincode::deserialize::<SymbolLocations>(&self.symbol_locations)?;
        Ok(symbol_locations)
    }
    pub fn hoverable_ranges(&self) -> Option<Vec<TextRange>> {
        CodeFileAST::build_ast(self.content.as_bytes(), self.lang.as_ref()?)
            .and_then(CodeFileAST::hoverable_ranges)
            .ok()
    }
}

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
        let mut new_start;
        let mut new_end;

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

    /// Constructs a hierarchical view of the code structure starting from a given node,
    /// moving upward through its parent scopes until it reaches the root level.
    /// Each line of code associated with a node is indented to reflect its depth in the hierarchy,
    /// and ellipses ("..") are included to represent skipped lines of code for readability.
    ///
    /// # Example
    ///
    /// Given a sample file content (a simplified representation of a code structure):
    ///
    /// ```plaintext
    /// 1: mod my_module {
    /// 2:     fn my_function() {
    /// 3:         println!("Hello, world!");
    /// 4:     }
    /// 5: }
    /// ```
    ///
    /// And a starting node corresponding to the line `println!("Hello, world!");`
    ///
    /// The output of `get_scope_map` would be:
    ///
    /// ```plaintext
    /// <Root Scope Line number 1> mod my_module {
    ///     <Line number 2> fn my_function() {
    ///         <Line number 3> println!("Hello, world!");
    ///         ..
    ///     }
    ///     ..
    /// }
    /// ```
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
        let mut current_node = start;
        let mut code_blocks = Vec::new();
        let mut depth = 0; // Depth of nesting
        let mut last_added_line_number: Option<usize> = None;

        while !self.is_top_level(current_node) {
            let (line, line_number) =
                self.get_code_line(current_node, file_content, line_end_indices);
            let indent = "    ".repeat(depth);

            // Ensure ellipses are added for skipped line numbers.
            if let Some(last_line) = last_added_line_number {
                if last_line + 1 < line_number {
                    code_blocks.push(format!("{}..", indent));
                }
            }

            // Add the line of code if it's not repeating the last line number.
            if last_added_line_number.map_or(true, |last_line| last_line != line_number) {
                code_blocks.push(format!("{}<Line number {}> {}", indent, line_number, line));
                last_added_line_number = Some(line_number);
            }

            // Move to the parent scope and increase depth.
            if let Some(parent) = self.parent_scope(current_node) {
                current_node = parent;
                depth += 1;
            } else {
                break;
            }
        }

        // Add the root scope's first line of code assuming it always starts from line 1, byte 0.
        if self.is_top_level(current_node) {
            // No indent for the root level.
            let root_line = &file_content[0..line_end_indices[0]];
            code_blocks.push(format!("<Root Scope Line number 1> {}", root_line));
        }

        code_blocks.reverse();
        code_blocks.join("\n")
    }
}
