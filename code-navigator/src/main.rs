use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::anyhow;
use anyhow::Result;
use stack_graphs::arena::Handle;
use stack_graphs::graph::File;
use stack_graphs::graph::StackGraph;
use stack_graphs::partial::PartialPaths;
use stack_graphs::serde::Filter;
use stack_graphs::stitching::Database;
use stack_graphs::stitching::DatabaseCandidates;
use stack_graphs::stitching::ForwardPartialPathStitcher;
use stack_graphs::stitching::StitcherConfig;
use stack_graphs::NoCancellation as SGNC;
use tree_sitter_stack_graphs::loader::{
    ContentProvider, FileReader, LanguageConfiguration, LoadError, Loader,
};
use tree_sitter_stack_graphs::test::Test;
use tree_sitter_stack_graphs::CancellationFlag;
use tree_sitter_stack_graphs::NoCancellation;
use tree_sitter_stack_graphs::Variables;

// This documentation test is not meant to test Python's actual stack graph
// construction rules.  An empty TSG file is perfectly valid (it just won't produce any stack
// graph content).  This minimizes the amount of work that we do when running `cargo test`.
static STACK_GRAPH_RULES: &str = "";

// fn main() -> Result<(), Box<dyn std::error::Error>> {
//     let python_source = r#"
//     import sys
//     print(sys.path)
//     "#;
//     let grammar = tree_sitter_python::language();
//     let tsg_source = STACK_GRAPH_RULES;
//     let mut language = StackGraphLanguage::from_str(grammar, tsg_source)?;
//     let mut stack_graph = StackGraph::new();
//     let file_handle = stack_graph.get_or_create_file("test.py");
//     let globals = Variables::new();
//     language.build_stack_graph_into(
//         &mut stack_graph,
//         file_handle,
//         python_source,
//         &globals,
//         &NoCancellation,
//     )?;
//     Ok(())
// }

/// The stack graphs tsg source for this language.
pub const STACK_GRAPHS_TSG_PATH: &str = "./languages/python/stack-graphs.tsg";
/// The stack graphs tsg source for this language.
pub const STACK_GRAPHS_TSG_SOURCE: &str = include_str!("./languages/python/stack-graphs.tsg");

/// The stack graphs builtins configuration for this language.
pub const STACK_GRAPHS_BUILTINS_CONFIG: &str = include_str!("./languages/python/builtins.cfg");
/// The stack graphs builtins path for this language
pub const STACK_GRAPHS_BUILTINS_PATH: &str = "./languages/python/builtins.py";
/// The stack graphs builtins source for this language.
pub const STACK_GRAPHS_BUILTINS_SOURCE: &str = include_str!("./languages/python/builtins.py");

/// The test python files for this language.
pub const TESTS_PATH: &str = "./src/languages/python/tests";

/// The name of the file path global variable.
pub const FILE_PATH_VAR: &str = "FILE_PATH";

pub fn language_configuration(
    cancellation_flag: &dyn CancellationFlag,
) -> Result<LanguageConfiguration, LoadError> {
    LanguageConfiguration::from_sources(
        tree_sitter_python::language(),
        Some(String::from("source.py")),
        None,
        vec![String::from("py")],
        STACK_GRAPHS_TSG_PATH.into(),
        STACK_GRAPHS_TSG_SOURCE,
        Some((
            STACK_GRAPHS_BUILTINS_PATH.into(),
            STACK_GRAPHS_BUILTINS_SOURCE,
        )),
        Some(STACK_GRAPHS_BUILTINS_CONFIG),
        cancellation_flag,
    )
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    print!("Hello World!");
    let test_path = PathBuf::from(TESTS_PATH);
    let lc = language_configuration(&NoCancellation)?;
    let mut loader =
            Loader::from_language_configurations(vec![lc], None).expect("Expected loader");
    Tester::new(vec![test_path]).run(loader);

    Ok(())
}

pub struct Tester {
    configurations: Vec<LanguageConfiguration>,
    test_paths: Vec<PathBuf>,
    pub max_test_time: Option<Duration>,
}

struct MappingFileReader<'a> {
    inner: FileReader,
    instead_of: &'a Path,
    load: &'a Path,
}

impl<'a> MappingFileReader<'a> {
    fn new(instead_of: &'a Path, load: &'a Path) -> Self {
        Self {
            inner: FileReader::new(),
            instead_of,
            load,
        }
    }

    fn get(&mut self, path: &Path) -> std::io::Result<&str> {
        let path = if path == self.instead_of {
            self.load
        } else {
            path
        };
        self.inner.get(path)
    }
}

impl ContentProvider for MappingFileReader<'_> {
    fn get(&mut self, path: &Path) -> std::io::Result<Option<&str>> {
        self.get(path).map(Some)
    }
}

impl Tester {
    pub fn new(test_paths: Vec<PathBuf>) -> Self {
        Self {
            configurations: Vec::new(),
            test_paths,
            max_test_time: Some(Duration::from_secs(60)),
        }
    }

    pub fn iter_files_and_directories<'a, P, IP>(
        paths: IP,
    ) -> impl Iterator<Item = (PathBuf, PathBuf, bool)> + 'a
    where
        P: AsRef<Path> + 'a,
        IP: IntoIterator<Item = P> + 'a,
    {
        paths
            .into_iter()
            .filter_map(
                |source_path| -> Option<Box<dyn Iterator<Item = (PathBuf, PathBuf, bool)>>> {
                    if source_path.as_ref().is_dir() {
                        let source_root = source_path;
                        let paths = walkdir::WalkDir::new(&source_root)
                            .follow_links(true)
                            .sort_by_file_name()
                            .into_iter()
                            .filter_map(|e| e.ok())
                            .filter(|e| e.file_type().is_file())
                            .map(move |e| {
                                (source_root.as_ref().to_path_buf(), e.into_path(), false)
                            });
                        Some(Box::new(paths))
                    } else {
                        let source_root = source_path
                            .as_ref()
                            .parent()
                            .expect("expect file to have parent");
                        Some(Box::new(std::iter::once((
                            source_root.to_path_buf(),
                            source_path.as_ref().to_path_buf(),
                            true,
                        ))))
                    }
                },
            )
            .flatten()
    }

    pub fn run(self, mut loader: Loader) -> anyhow::Result<()> {
        // let configurations = Loader::from_language_configurations(self.configurations, None);
        let test_paths = self
            .test_paths
            .clone()
            .into_iter()
            .map(|test_path| {
                std::env::current_dir()
                    .ok()
                    .and_then(|cwd| pathdiff::diff_paths(&test_path, &cwd))
                    .unwrap_or(test_path)
            })
            .collect::<Vec<_>>();
        for test_path in &test_paths {
            if !test_path.exists() {
                panic!("Test path {} does not exist, currenct dir is {}", test_path.display(), std::env::current_dir().unwrap().display());
            }
        }
        // let mut loader =
        //     Loader::from_language_configurations(self.configurations, None).expect("Expected loader");

        // Tester::iter_files_and_directories(self.test_paths.clone())
        //     .into_iter()
        //     .for_each(|(test_root, test_path, _)| {
        //         let test_result = self
        //             .run_test_inner(&test_root, &test_path, &mut loader)
        //             .map_err(|e| e);
        //     });

        // let loader = self.loader;
        self.run_tests(&test_paths[0], &test_paths, &mut loader);

        Ok(())
    }

    fn run_tests(
        &self,
        test_root: &Path,
        test_paths: &[PathBuf],
        mut loader: &mut Loader,
    ) -> anyhow::Result<()> {
        for (test_root, test_path, _) in Tester::iter_files_and_directories(test_paths.clone()) {
            let test_result = self.run_test_inner(&test_root, &test_path, &mut loader);
        }
        Ok(())
    }



    fn run_test_inner(
        &self,
        test_root: &Path,
        test_path: &Path,
        loader: &mut Loader,
    ) -> anyhow::Result<()> {
        let mut cancellation_flag = NoCancellation;

        // If the file is skipped (ending in .skip) we construct the non-skipped path to see if we would support it.
        let load_path = if test_path.extension().map_or(false, |e| e == "skip") {
            test_path.with_extension("")
        } else {
            test_path.to_path_buf()
        };
        let mut file_reader = MappingFileReader::new(&load_path, test_path);
        let lc = match loader
            .load_for_file(&load_path, &mut file_reader, &cancellation_flag)?
            .primary
        {
            Some(lc) => lc,
            None => return Ok(()),
        };

        if test_path.components().any(|c| match c {
            std::path::Component::Normal(name) => (name.as_ref() as &Path)
                .extension()
                .map_or(false, |e| e == "skip"),
            _ => false,
        }) {
            print!("Skipping test {}", test_path.display());
            return Ok(());
        }

        print!("Running test {}", test_path.display());

        let source = file_reader.get(test_path)?;
        let default_fragment_path = test_path.strip_prefix(test_root).unwrap();
        let mut test = Test::from_source(test_path, source, default_fragment_path)?;

        self.load_builtins_into(&lc, &mut test.graph)?;

        let mut globals = Variables::new();
        for test_fragment in &test.fragments {
            let result = if let Some(fa) = test_fragment
                .path
                .file_name()
                .and_then(|file_name| lc.special_files.get(&file_name.to_string_lossy()))
            {
                let mut all_paths = test.fragments.iter().map(|f| f.path.as_path());
                fa.build_stack_graph_into(
                    &mut test.graph,
                    test_fragment.file,
                    &test_fragment.path,
                    &test_fragment.source,
                    &mut all_paths,
                    &test_fragment.globals,
                    &cancellation_flag,
                )
            } else if lc.matches_file(
                &test_fragment.path,
                &mut Some(test_fragment.source.as_ref()),
            )? {
                globals.clear();
                test_fragment.add_globals_to(&mut globals);
                lc.sgl.build_stack_graph_into(
                    &mut test.graph,
                    test_fragment.file,
                    &test_fragment.source,
                    &globals,
                    &cancellation_flag,
                )
            } else {
                return Err(anyhow!(
                    "Test fragment {} not supported by language of test file {}",
                    test_fragment.path.display(),
                    test.path.display()
                ));
            };
            match result {
                Err(err) => {
                    print!("Failed to build graph for {}: {}", test_path.display(), err);
                    return Err(anyhow!("Failed to build graph for {}", test_path.display()));
                }
                Ok(_) => {}
            }
        }
        let stitcher_config =
            StitcherConfig::default().with_detect_similar_paths(!lc.no_similar_paths_in_file);
        let mut partials = PartialPaths::new();
        let mut db = Database::new();
        for file in test.graph.iter_files() {
            ForwardPartialPathStitcher::find_minimal_partial_path_set_in_file(
                &test.graph,
                &mut partials,
                file,
                stitcher_config,
                &SGNC,
                |g, ps, p| {
                    db.add_partial_path(g, ps, p.clone());
                },
            )?;
        }
        let result = test.run(&mut partials, &mut db, stitcher_config, &cancellation_flag)?;
        let success = result.failure_count() == 0;
        let outputs = if true {
            let files = test.fragments.iter().map(|f| f.file).collect::<Vec<_>>();
            self.save_output(
                test_root,
                test_path,
                &test.graph,
                &mut partials,
                &mut db,
                &|_: &StackGraph, h: &Handle<File>| files.contains(h),
                success,
                stitcher_config,
                &cancellation_flag,
            )?
        } else {
            Vec::default()
        };

        if success {
            let details = outputs.join("\n");
            print!("{}/{} assertions passed", result.count(), result.count());
        } else {
            let details = result
                .failures_iter()
                .map(|f| f.to_string())
                .chain(outputs)
                .for_each(|f| print!("{}", f));
            print!(
                "{}/{} assertions failed",
                result.failure_count(),
                result.count()
            );
        }

        Ok(())
    }

    fn load_builtins_into(
        &self,
        lc: &LanguageConfiguration,
        graph: &mut StackGraph,
    ) -> anyhow::Result<()> {
        if let Err(h) = graph.add_from_graph(&lc.builtins) {
            return Err(anyhow!("Duplicate builtin file {}", &graph[h]));
        }
        Ok(())
    }

    fn save_output(
        &self,
        test_root: &Path,
        test_path: &Path,
        graph: &StackGraph,
        partials: &mut PartialPaths,
        db: &mut Database,
        filter: &dyn Filter,
        success: bool,
        stitcher_config: StitcherConfig,
        cancellation_flag: &dyn CancellationFlag,
    ) -> anyhow::Result<Vec<String>> {
        let mut outputs = Vec::with_capacity(3);
        let save_graph_format = "%n.graph.json".to_string();
        let save_paths_format = "%n.paths.json".to_string();
        let save_visualization_format = "%n.html".to_string();

        let save_graph = Some(&save_graph_format).map(|format| {
            format
                .replace("%r", test_root.to_str().unwrap())
                .replace("%n", test_path.file_name().unwrap().to_str().unwrap())
        });
        let save_paths = Some(&save_paths_format).map(|format| {
            format
                .replace("%r", test_root.to_str().unwrap())
                .replace("%n", test_path.file_name().unwrap().to_str().unwrap())
        });
        let save_visualization = Some(&save_visualization_format).map(|format| {
            format
                .replace("%r", test_root.to_str().unwrap())
                .replace("%n", test_path.file_name().unwrap().to_str().unwrap())
        });

        if let Some(path) = save_graph {
            self.save_graph(Path::new(&path), graph, filter)?;
            if !success {
                outputs.push(format!("{}: graph at {}", test_path.display(), path));
            }
        }

        let mut db = if save_paths.is_some() || save_visualization.is_some() {
            self.compute_paths(
                graph,
                partials,
                db,
                filter,
                stitcher_config,
                cancellation_flag,
            )?
        } else {
            Database::new()
        };

        if let Some(path) = save_paths {
            self.save_paths(Path::new(&path), graph, partials, &mut db, filter)?;
            if !success {
                outputs.push(format!("{}: paths at {}", test_path.display(), path));
            }
        }

        if let Some(path) = save_visualization {
            self.save_visualization(Path::new(&path), graph, partials, &mut db, filter, test_path)?;
            if !success {
                outputs.push(format!(
                    "{}: visualization at {}",
                    test_path.display(),
                    path
                ));
            }
        }
        Ok(outputs)
    }

    fn save_graph(
        &self,
        path: &Path,
        graph: &StackGraph,
        filter: &dyn Filter,
    ) -> anyhow::Result<()> {
        let json = serde_json::to_string_pretty(&graph.to_serializable_filter(filter))?;
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(&path, json)?;
        Ok(())
    }

    fn compute_paths(
        &self,
        graph: &StackGraph,
        partials: &mut PartialPaths,
        db: &mut Database,
        filter: &dyn Filter,
        stitcher_config: StitcherConfig,
        cancellation_flag: &dyn CancellationFlag,
    ) -> anyhow::Result<Database> {
        let references = graph
            .iter_nodes()
            .filter(|n| filter.include_node(graph, n))
            .collect::<Vec<_>>();
        let mut paths = Vec::new();
        ForwardPartialPathStitcher::find_all_complete_partial_paths(
            &mut DatabaseCandidates::new(graph, partials, db),
            references.clone(),
            stitcher_config,
            &cancellation_flag,
            |_, _, p| {
                paths.push(p.clone());
            },
        )?;
        let mut db = Database::new();
        for path in paths {
            db.add_partial_path(graph, partials, path);
        }
        Ok(db)
    }

    fn save_paths(
        &self,
        path: &Path,
        graph: &StackGraph,
        partials: &mut PartialPaths,
        db: &mut Database,
        filter: &dyn Filter,
    ) -> anyhow::Result<()> {
        let json =
            serde_json::to_string_pretty(&db.to_serializable_filter(graph, partials, filter))?;
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(&path, json)?;
        Ok(())
    }

    fn save_visualization(
        &self,
        path: &Path,
        graph: &StackGraph,
        paths: &mut PartialPaths,
        db: &mut Database,
        filter: &dyn Filter,
        test_path: &Path,
    ) -> anyhow::Result<()> {
        let html = graph.to_html_string(&format!("{}", test_path.display()), paths, db, filter)?;
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(&path, html)?;
        Ok(())
    }
}
