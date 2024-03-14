extern crate hashbrown;
extern crate strsim;

use crate::search::payload::{CodeExtractMeta, PathExtractMeta, SymbolPayload};
use hashbrown::HashMap;
use strsim::levenshtein;

// declare global variable for POWF_FACTOR
const POWF_FACTOR: f32 = 3.0;

// create a table for weights of symbols
pub fn symbol_weights() -> HashMap<String, f32> {
    let mut weights = HashMap::new();
    weights.insert("variable".to_string(), 1.0);
    weights.insert("function".to_string(), 9.0);
    weights.insert("module".to_string(), 8.0);
    weights.insert("struct".to_string(), 8.0);
    weights.insert("field".to_string(), 3.0);
    weights.insert("unknown".to_string(), 2.0);
    weights.clone()
}

pub fn rank_symbol_payloads(payloads: &Vec<SymbolPayload>) -> Vec<PathExtractMeta> {
    let mut path_scores: HashMap<String, f32> = HashMap::new();
    let mut path_history: HashMap<String, Vec<String>> = HashMap::new();
    // create map to store the relative_path + symbol string and count the number of times it appears.
    let mut path_symbol_set: HashMap<String, usize> = HashMap::new();

    let mut code_extract_meta_map: HashMap<String, Vec<CodeExtractMeta>> = HashMap::new();

    for (i, val) in payloads.iter().enumerate() {
        let payload = &payloads[i];
        let score = payload.score.unwrap_or(0.0);
        // check if node_type is "ref"
        for (index, path) in payload.relative_paths.iter().enumerate() {
            let mut path_score = 0.0;
            let mut history = Vec::new();
            // print the node type and path
            println!(" in loop {}: {}", payload.node_kinds[index], path);
            // print symbol type and is global
            println!(
                "in loop {}: {}",
                payload.symbol_types[index], payload.is_globals[index]
            );

            // print if the symbol type is ref
            if payload.node_kinds[index] == "ref".to_string() {
                println!("xxxxxx ref is here");
            }
            // concatenate the relative_path and symbol string and store in path_symbol
            let path_symbol = format!("{}{}", path, payload.symbol);
            // check if path_symbol is in path_symbol_set
            if path_symbol_set.contains_key(&path_symbol) {
                // if it is, increment the count by 1
                *path_symbol_set.get_mut(&path_symbol).unwrap() += 1;
            } else {
                // if it is not, add it to the map with a count of 1
                path_symbol_set.insert(path_symbol.clone(), 1);
            }

            // if path_symbol is greater than 3 just print and continue
            if path_symbol_set[&path_symbol] > 3 {
                let repeat_bonus = 1000.0 * score.powf(5.0);
                // add a bonus score of 1000.0
                path_score += repeat_bonus;
                // push to history
                history.push(format!(
                    "Scored {} for repeat symbol {} with score {}",
                    repeat_bonus, payload.symbol, score
                ));

                // store the metadata of a symbol for a given path,
                // and the contribution of the symbol to the path's score.
                let code_extract_meta = CodeExtractMeta {
                    symbol: payload.symbol.clone(),
                    node_kind: payload.node_kinds[index].clone(),
                    symbol_type: payload.symbol_types[index].clone(),
                    is_global: payload.is_globals[index],
                    score: path_score,
                    start_byte: payload.start_bytes[index],
                    end_byte: payload.end_bytes[index],
                };

                // store the metadata in the code_extract_meta map
                code_extract_meta_map
                    .entry(path.clone())
                    .or_insert(Vec::new())
                    .push(code_extract_meta);

                *path_scores.entry(path.clone()).or_insert(0.0) += path_score;
                path_history
                    .entry(path.clone())
                    .or_insert(Vec::new())
                    .append(&mut history);
                println!(
                    "Greater than 3 {}: {}: {}",
                    path_symbol, path_symbol_set[&path_symbol], repeat_bonus
                );
                continue;
            }

            // Score based on the type of symbol
            match payload.symbol_types[index].as_str() {
                "variable" => path_score += 1.0,
                "function" => path_score += 9.0,
                "module" => path_score += 8.0,
                "struct" => path_score += 8.0,
                "field" => path_score += 3.0,
                // print the type and add score of 2.0
                _ => {
                    println!("Unknown symbol type: {}", payload.symbol_types[index]);
                    path_score += 2.0;
                }
            }

            // multiple path_score by score power of three
            path_score = path_score * score;
            history.push(format!(
                "Scored {} for symbol {} symbol type {}",
                path_score, payload.symbol, payload.symbol_types[index]
            ));

            // Score based on is_global
            if payload.is_globals[index] {
                let global_score = 500.0 * score.powf(5.0);
                path_score += global_score;
                history.push(format!(
                    "Scored {} for global symbol {} with score {}",
                    global_score, payload.symbol, score
                ));
            }

            // Score based on the semantic score, if available
            if let Some(semantic_score) = payload.score {
                if semantic_score > 0.35 {
                    let bonus = (semantic_score.powf(2.0) * (1.0 + score).powf(POWF_FACTOR))
                        * (path_score / 10.0);
                    path_score += bonus;
                    history.push(format!(
                        "Scored {} for semantic score {} for symbol {}",
                        bonus, semantic_score, payload.symbol
                    ));
                }
            }

            // If path_symbol is greater than 1 continue the loop, dont do any operation
            if path_symbol_set[&path_symbol] > 1 {
                // give a bonus and continue
                let repeat_bonus = 200.0 * score.powf(5.0);
                println!(
                    "Greater than 1 {}: {}: {}",
                    path_symbol, path_symbol_set[&path_symbol], repeat_bonus
                );
                // push to history and print
                path_score += repeat_bonus;
                history.push(format!(
                    "Scored {} for repeat symbol {} with score {}",
                    repeat_bonus, payload.symbol, score
                ));
                println!("Skipping {} because it is greater than 1", path_symbol);
                // store the metadata of a symbol for a given path,
                // and the contribution of the symbol to the path's score.
                let code_extract_meta = CodeExtractMeta {
                    symbol: payload.symbol.clone(),
                    node_kind: payload.node_kinds[index].clone(),
                    symbol_type: payload.symbol_types[index].clone(),
                    is_global: payload.is_globals[index],
                    score: path_score,
                    start_byte: payload.start_bytes[index],
                    end_byte: payload.end_bytes[index],
                };

                // store the metadata in the code_extract_meta map
                code_extract_meta_map
                    .entry(path.clone())
                    .or_insert(Vec::new())
                    .push(code_extract_meta);

                *path_scores.entry(path.clone()).or_insert(0.0) += path_score;
                path_history
                    .entry(path.clone())
                    .or_insert(Vec::new())
                    .append(&mut history);
                continue;
            }

            // Check for symbol similarities with other payloads
            for j in (i + 1)..payloads.len() {
                let other_payload = &payloads[j];

                // Check if one symbol is a substring of another
                if payload.symbol.contains(&other_payload.symbol)
                    || other_payload.symbol.contains(&payload.symbol)
                {
                    let substr_score = 10.0 * score.powf(POWF_FACTOR);
                    path_score += substr_score;
                    history.push(format!(
                        "Scored {} for symbol {} being a substring of {}, in parent path {}",
                        substr_score, payload.symbol, other_payload.symbol, path
                    ));
                }

                let distance = levenshtein(&payload.symbol, &other_payload.symbol);
                if distance < 3 {
                    let levenshtein_score = 5.0 * score.powf(POWF_FACTOR);
                    path_score += levenshtein_score;
                    history.push(format!(
                        "Scored {} for low Levenshtein distance of {} between symbols {} and {}",
                        levenshtein_score, distance, payload.symbol, other_payload.symbol
                    ));
                }
            }

            // store the metadata of a symbol for a given path,
            // and the contribution of the symbol to the path's score.
            let code_extract_meta = CodeExtractMeta {
                symbol: payload.symbol.clone(),
                node_kind: payload.node_kinds[index].clone(),
                symbol_type: payload.symbol_types[index].clone(),
                is_global: payload.is_globals[index],
                score: path_score,
                start_byte: payload.start_bytes[index],
                end_byte: payload.end_bytes[index],
            };

            // store the metadata in the code_extract_meta map
            code_extract_meta_map
                .entry(path.clone())
                .or_insert(Vec::new())
                .push(code_extract_meta);

            *path_scores.entry(path.clone()).or_insert(0.0) += path_score;
            path_history
                .entry(path.clone())
                .or_insert(Vec::new())
                .append(&mut history);
        }
    }

    // contruct PathExtractMeta from the data
    let mut final_scores: Vec<PathExtractMeta> = path_scores
        .iter()
        .map(|(path, &score)| {
            // get the value for path from code_extract_meta_map and sort the value array by score
            let mut code_extract_meta = code_extract_meta_map.get(path).unwrap().clone();
            code_extract_meta.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
            PathExtractMeta {
                path: path.clone(),
                score: score,
                history: path_history.get(path).unwrap().clone(),
                code_extract_meta: code_extract_meta.clone(),
            }
        })
        .collect();

    // Sort the paths by their computed scores, in descending order
    final_scores.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());

    final_scores
}
