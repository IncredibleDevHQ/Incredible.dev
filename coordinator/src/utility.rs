use std::ops::Range;
use ai_gateway::{config::AIGatewayConfig, message::message::Message};
use anyhow::Result;
use log::debug;

use crate::configuration::get_ai_gateway_config;

pub async fn call_llm(user_msg: Option<String>, history: Option<Vec<Message>>) -> Result<String> {
    let config = get_ai_gateway_config();
    let mut ai_gateway_config = AIGatewayConfig::from_yaml(&config)?;
    let result = ai_gateway_config
        .use_llm(user_msg, history, None, true, false)
        .await?;

    debug!("LLM response: {}", result);
    Ok(result)
}

fn merge_ranges(ranges: &[Range<usize>]) -> Vec<Range<usize>> {
    let mut sorted_ranges = ranges.to_vec();
    sorted_ranges.sort_by_key(|r| r.start);

    let mut merged_ranges: Vec<Range<usize>> = vec![];

    for range in sorted_ranges.iter() {
        if let Some(last) = merged_ranges.last_mut() {
            // If the current range overlaps with the last range in merged_ranges, merge them.
            if last.end >= range.start {
                last.end = last.end.max(range.end);
            } else {
                merged_ranges.push(range.clone());
            }
        } else {
            // If merged_ranges is empty, just add the current range.
            merged_ranges.push(range.clone());
        }
    }

    merged_ranges
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_merge_ranges() {
        let ranges = vec![
            Range { start: 1, end: 3 },
            Range { start: 2, end: 6 },
            Range { start: 8, end: 10 },
            Range { start: 7, end: 8 },
        ];

        let expected_merged_ranges = vec![Range { start: 1, end: 6 }, Range { start: 7, end: 10 }];

        let merged_ranges = merge_ranges(&ranges);

        assert_eq!(merged_ranges, expected_merged_ranges);
    }

    #[test]
    fn test_merge_ranges_no_overlap() {
        let ranges = vec![
            Range { start: 1, end: 2 },
            Range { start: 3, end: 4 },
            Range { start: 5, end: 6 },
        ];

        // Expect no change as there are no overlapping ranges.
        let expected_merged_ranges = ranges.clone();

        let merged_ranges = merge_ranges(&ranges);

        assert_eq!(merged_ranges, expected_merged_ranges);
    }

    #[test]
    fn test_merge_ranges_single_range() {
        let ranges = vec![Range { start: 1, end: 5 }];

        // Expect the same single range back.
        let expected_merged_ranges = ranges.clone();

        let merged_ranges = merge_ranges(&ranges);

        assert_eq!(merged_ranges, expected_merged_ranges);
    }

    #[test]
    fn test_merge_ranges_empty() {
        let ranges: Vec<Range<usize>> = vec![];

        // Expect an empty vector back.
        let expected_merged_ranges: Vec<Range<usize>> = vec![];

        let merged_ranges = merge_ranges(&ranges);

        assert_eq!(merged_ranges, expected_merged_ranges);
    }
}
