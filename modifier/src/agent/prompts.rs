pub fn diff_prompt(context_formatted: &str) -> String {
    format!(
        r#"Below are files from a codebase. Your job is to write a Unified Format patch to complete a provided task. To write a unified format patch, surround it in a code block: ```diff

Follow these rules strictly:
- Diff paths follow the format `github.com/org/repo:path/to/file.js` for remote repositories, or `local//path/to/repo:path/to/file.js` for local repositories. Make sure to include these in your diff.
- You MUST only return a single diff block, no additional commentary.
- Keep hunks concise only include a short context for each hunk. 
- ALWAYS respect input whitespace, to ensure diffs can be applied cleanly!
- Only generate diffs that can be applied by `patch`! NO extra information like `git` commands
- To add a new file, set the input file as /dev/null
- To remove an existing file, set the output file to /dev/null

# Example outputs

```diff
--- github.com/BloopAI/tutorial:src/index.js
+++ github.com/BloopAI/tutorial:src/index.js
@@ -10,5 +10,5 @@
 const maybeHello = () => {{
     if (Math.random() > 0.5) {{
-        console.log("hello world!")
+        console.log("hello?")
     }}
 }}
```

```diff
--- local//Users/blooper/dev/bloop:README.md
+++ local//Users/blooper/dev/bloop:README.md
@@ -1,3 +1,3 @@
 # Bloop AI
 
-bloop is ChatGPT for your code. Ask questions in natural language, search for code and generate patches using your existing codebase as context.
+bloop is ChatGPT for your code. Ask questions in natural language, search for code and generate patches using your existing code base as context.
```

```diff
--- github.com/BloopAI/bloop:client/src/locales/en.json
+++ github.com/BloopAI/bloop:client/src/locales/en.json
@@ -21,5 +21,5 @@
 	"Report a bug": "Report a bug",
 	"Sign In": "Sign In",
-	"Sign in with GitHub": "Sign in with GitHub",
+	"Sign in via GitHub": "Sign in via GitHub",
 	"Status": "Status",
 	"Submit bug report": "Submit bug report",
```

Adding a new file:

```diff
--- /dev/null
+++ local//tmp/test-project:src/sum.rs
@@ -0,0 +1,3 @@
+fn sum(a: f32, b: f32) -> f32 {{
+    a + b
+}}
```

Removing an existing file:

```diff
--- local//tmp/another-project:src/div.rs
+++ /dev/null
@@ -1,3 +0,0 @@
-fn div(a: f32, b: f32) -> f32 {{
-    a / b
-}}
```

#####

{context_formatted}"#
    )
}

pub fn studio_diff_regen_hunk_prompt(context_formatted: &str) -> String {
    format!(
        r#"The provided diff contains no context lines. Output a new hunk with the correct 3 context lines.

Here is the full context for reference:

#####

{context_formatted}"#
    )
}
