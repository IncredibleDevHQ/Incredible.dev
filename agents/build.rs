use std::{
    collections::HashMap,
    env,
    ffi::OsStr,
    fs::File,
    io::{BufWriter, Write},
    path::Path,
};

extern crate phf;
extern crate phf_codegen;




#[derive(serde::Deserialize)]
struct Language {
    r#type: String,
    aliases: Option<Vec<String>>,
}
fn main() {
 
    process_languages();
    println!("cargo:rerun-if-changed=migrations");
}


fn process_languages() {
    let langs_file = File::open("./languages.yml").unwrap();
    let langs: HashMap<String, Language> = serde_yaml::from_reader(langs_file).unwrap();

    let languages_path = Path::new(&env::var("OUT_DIR").unwrap()).join("languages.rs");
    let mut ext_map = phf_codegen::Map::new();
    let mut case_map = phf_codegen::Map::new();

    for (name, data) in langs
        .into_iter()
        .filter(|(_, d)| d.r#type == "programming" || d.r#type == "prose")
    {
        let name_lower = name.to_ascii_lowercase();

        for alias in data.aliases.unwrap_or_default() {
            ext_map.entry(alias, &format!("\"{name_lower}\""));
        }

        case_map.entry(name_lower, &format!("\"{name}\""));
    }

    write!(
        BufWriter::new(File::create(languages_path).unwrap()),
        "static EXT_MAP: phf::Map<&str, &str> = \n{};\n\
         static PROPER_CASE_MAP: phf::Map<&str, &str> = \n{};\n",
        ext_map.build(),
        case_map.build(),
    )
    .unwrap();

    println!("cargo:rerun-if-changed=../languages.yml");
}
