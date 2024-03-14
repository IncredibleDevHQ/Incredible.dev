use regex;

pub fn build_fuzzy_regex_filter(query_str: &str) -> Option<regex::RegexSet> {
    fn additions(s: &str, i: usize, j: usize) -> String {
        if i > j {
            additions(s, j, i)
        } else {
            let mut s = s.to_owned();
            s.insert_str(j, ".?");
            s.insert_str(i, ".?");
            s
        }
    }

    fn replacements(s: &str, i: usize, j: usize) -> String {
        if i > j {
            replacements(s, j, i)
        } else {
            let mut s = s.to_owned();
            s.remove(j);
            s.insert_str(j, ".?");

            s.remove(i);
            s.insert_str(i, ".?");

            s
        }
    }

    fn one_of_each(s: &str, i: usize, j: usize) -> String {
        if i > j {
            one_of_each(s, j, i)
        } else {
            let mut s = s.to_owned();
            s.remove(j);
            s.insert_str(j, ".?");

            s.insert_str(i, ".?");
            s
        }
    }

    let all_regexes = (query_str.char_indices().map(|(idx, _)| idx))
        .flat_map(|i| (query_str.char_indices().map(|(idx, _)| idx)).map(move |j| (i, j)))
        .filter(|(i, j)| i <= j)
        .flat_map(|(i, j)| {
            let mut v = vec![];
            if j != query_str.len() {
                v.push(one_of_each(query_str, i, j));
                v.push(replacements(query_str, i, j));
            }
            v.push(additions(query_str, i, j));
            v
        });

    regex::RegexSetBuilder::new(all_regexes)
        // Increased from the default to account for long paths. At the time of writing,
        // the default was `10 * (1 << 20)`.
        .size_limit(10 * (1 << 25))
        .case_insensitive(true)
        .build()
        .ok()
}
