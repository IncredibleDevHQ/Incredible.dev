;; -*- coding: utf-8 -*-
;; ------------------------------------------------------------------------------------------------
;; Copyright © 2023, stack-graphs authors.
;; Licensed under either of Apache License, Version 2.0, or MIT license, at your option.
;; Please see the LICENSE-APACHE or LICENSE-MIT files in this distribution for license details.
;; ------------------------------------------------------------------------------------------------

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; LEGACY DEFINITION! INCLUDED FOR REFERENCE ONLY! ;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

; Modules and Imports
;---------------------

(module) @mod
{
  var module_def = @mod.file_def
  attr module_def "no_span"
  var module_ref = @mod.file_ref
  attr module_ref "no_span"
  var parent_module_def = module_def
  var parent_module_ref = module_ref
  var grandparent_module_ref = module_ref

  scan filepath {
    "([^/]+)/"
    {
      edge module_def -> module_def.dot
      edge module_def.dot -> module_def.next_def
      edge module_ref.next_ref -> module_ref.dot
      edge module_ref.dot -> module_ref

      attr module_def "pop" = $1
      attr module_def.dot "pop" = "."
      attr module_ref "push" = $1
      attr module_ref.dot "push" = "."

      set grandparent_module_ref = parent_module_ref
      set parent_module_def = module_def
      set parent_module_ref = module_ref
      set module_ref = module_ref.next_ref
      set module_def = module_def.next_def
      attr module_def "no_span"
      attr module_ref "no_span"
    }

    "__init__\\.py$"
    {
      attr parent_module_def "definition"
    }

    "([^/]+)$"
    {
      edge module_def -> module_def.dot
      edge module_def.dot -> module_def.next_def

      attr module_def "definition", "pop" = (replace $1 "\\.py" "")
      attr module_def.dot "pop" = "."

      set module_def = module_def.next_def
      attr module_def "no_span"
      attr module_ref "no_span"
    }
  }

  edge root -> @mod.file_def
  edge @mod.file_ref -> root
  edge module_def -> @mod.after_scope

  edge @mod.before_scope -> @mod.global_dot
  edge @mod.global -> root
  attr @mod.global "push" = "<builtins>"

  edge @mod.global_dot -> @mod.global
  attr @mod.global_dot "push" = "."

  var @mod::parent_module = parent_module_ref
  var @mod::grandparent_module = grandparent_module_ref
  var @mod::bottom = @mod.after_scope
  var @mod::global = @mod.global
  var @mod::global_dot = @mod.global_dot
}

(import_statement
  name: (dotted_name
    . (identifier) @root_name)) @stmt
{
  edge @stmt.after_scope -> @root_name.def, "precedence" = 1
  edge @root_name.ref -> root
  attr @root_name.ref "push", "reference"
  attr @root_name.def "pop", "definition"
}

(import_statement
  name: (aliased_import
    (dotted_name . (identifier) @root_name))) @stmt
{
  edge @stmt.after_scope -> @root_name.def
  edge @root_name.ref -> root
  attr @root_name.ref "push", "reference"
}

(import_from_statement
  module_name: (dotted_name
    . (identifier) @prefix_root_name)) @stmt
{
  edge @prefix_root_name.ref -> root
  attr @prefix_root_name.ref "push", "reference"
}

(import_from_statement
  name: (dotted_name
    . (identifier) @import_root_name)) @stmt
{
  edge @stmt.after_scope -> @import_root_name.def, "precedence" = 1
  edge @import_root_name.ref -> @import_root_name.ref_dot
  attr @import_root_name.def "pop", "definition"
  attr @import_root_name.ref "push", "reference"
  attr @import_root_name.ref_dot "push" = "."
}

(import_from_statement
  name: (aliased_import
    (dotted_name
      . (identifier) @import_root_name))) @stmt
{
  edge @import_root_name.ref -> @import_root_name.ref_dot
  attr @import_root_name.ref "push", "reference"
  attr @import_root_name.ref_dot "push" = "."
}

(import_from_statement
  module_name: [
    (dotted_name (identifier) @prefix_leaf_name .)
    (relative_import (dotted_name (identifier) @prefix_leaf_name .))
    (relative_import (import_prefix) @prefix_leaf_name .)
  ]
  name: [
    (dotted_name
      . (identifier) @import_root_name)
    (aliased_import
      (dotted_name
        . (identifier) @import_root_name))
  ])
{
  edge @import_root_name.ref_dot -> @prefix_leaf_name.ref
}

[
  (import_from_statement
    (aliased_import
      name: (dotted_name (identifier) @name .)
      alias: (identifier) @alias))
  (import_statement
    (aliased_import
      name: (dotted_name (identifier) @name .)
      alias: (identifier) @alias))
] @stmt
{
  edge @stmt.after_scope -> @alias
  edge @alias -> @name.ref
  attr @alias "pop", "definition"
}

[
  (import_statement
    name: (dotted_name
      (identifier) @leaf_name .))
  (import_from_statement
    name: (dotted_name
      (identifier) @leaf_name .))
]
{
  attr @leaf_name.def "pop", "definition"
  attr @leaf_name.ref "push", "reference"
  edge @leaf_name.def -> @leaf_name.ref
}

(relative_import
  (import_prefix) @prefix
  (#eq? @prefix ".")) @import
{
  edge @prefix.ref -> @import::parent_module
}

(relative_import
  (import_prefix) @prefix
  (#eq? @prefix "..")) @import
{
  edge @prefix.ref -> @import::grandparent_module
}

(relative_import
  (import_prefix) @prefix
  (dotted_name
    . (identifier) @name))
{
  attr @name.ref "push", "reference"
  attr @name.ref_dot "push" = "."
  edge @name.ref -> @name.ref_dot
  edge @name.ref_dot -> @prefix.ref
}

[
  (import_from_statement
    module_name: (relative_import
      (dotted_name
        (identifier) @parent_name
        .
        (identifier) @child_name)))
  (import_from_statement
    module_name: (dotted_name
      (identifier) @parent_name
      .
      (identifier) @child_name))
]
{
  attr @child_name.ref "push", "reference"
  attr @child_name.ref_dot "push" = "."
  edge @child_name.ref -> @child_name.ref_dot
  edge @child_name.ref_dot -> @parent_name.ref
}

(import_from_statement
  module_name: (dotted_name
    . (identifier) @root_name))
{
  attr @root_name.ref "push", "reference"
  edge @root_name.ref -> root
}

(import_from_statement
  module_name: (dotted_name
    (identifier) @leaf_name .)
  (wildcard_import) @star) @stmt
{
  edge @stmt.after_scope -> @star.ref_dot, "precedence" = 1
  edge @star.ref_dot -> @leaf_name.ref
  attr @star.ref_dot "push" = "."
}

[
  (import_statement
    name: (dotted_name
      (identifier) @parent_name
      .
      (identifier) @child_name))
  (import_from_statement
    name: (dotted_name
      (identifier) @parent_name
      .
      (identifier) @child_name))
  (import_from_statement
    name: (aliased_import
      name: (dotted_name
        (identifier) @parent_name
        .
        (identifier) @child_name)))
]
{
  edge @child_name.ref -> @child_name.ref_dot
  edge @child_name.ref_dot -> @parent_name.ref
  edge @parent_name.def -> @parent_name.def_dot
  edge @parent_name.def_dot -> @child_name.def
  attr @child_name.def "pop", "definition"
  attr @child_name.ref "push","reference"
  attr @parent_name.def_dot "pop" = "."
  attr @child_name.ref_dot "push" = "."
}

;--------
; Scopes
;--------

[
  (module (_) @last_stmt .)
  (block (_) @last_stmt .)
] @block
{
  edge @block.after_scope -> @last_stmt.after_scope
}

[
  (module (_) @stmt1 . (_) @stmt2)
  (block (_) @stmt1 . (_) @stmt2)
]
{
  edge @stmt2.before_scope -> @stmt1.after_scope
}

[
  (module (_) @stmt)
  (block (_) @stmt)
]
{
  edge @stmt.after_scope -> @stmt.before_scope
  let @stmt::local_scope = @stmt.before_scope
}

[
  (block . (_) @stmt)
  (module . (_) @stmt)
] @block
{
  edge @stmt.before_scope -> @block.before_scope
}

(block (_) @stmt . ) @block
{
  edge @block.after_scope -> @stmt.after_scope
}

(function_definition (block) @block)
{
  edge @block.before_scope -> @block::local_scope
}

[
  (while_statement (block) @block)
  (if_statement (block) @block)
  (with_statement (block) @block)
  (try_statement (block) @block)
  (for_statement (block) @block)
  (_ [
    (else_clause (block) @block)
    (elif_clause (block) @block)
    (except_clause (block) @block)
    (finally_clause (block) @block)
  ])
] @stmt
{
  edge @block.before_scope -> @block::local_scope
  edge @stmt.after_scope -> @block.after_scope
}

(match_statement (case_clause) @block) @stmt
{
  let @block::local_scope = @block.before_scope
  edge @block.before_scope -> @stmt.before_scope
  edge @stmt.after_scope -> @block.after_scope
}

[
  (for_statement)
  (while_statement)
] @stmt
{
  edge @stmt.before_scope -> @stmt.after_scope
}

;-------------
; Definitions
;-------------

[
  (assignment
    left: (_) @pattern
    right: (_) @value)
  (with_item
    value:
      (as_pattern
        (_) @value
        alias: (as_pattern_target (_) @pattern)))
]
{
  edge @pattern.input -> @value.output
}

(function_definition
  name: (identifier) @name
  parameters: (parameters) @params
  body: (block) @body) @func
{
  attr @name "definiens" = @func
  edge @func.after_scope -> @name
  edge @name -> @func.call
  edge @func.call -> @func.return_value
  edge @body.before_scope -> @params.after_scope
  edge @body.before_scope -> @func.drop_scope
  edge @func.drop_scope -> @func::bottom
  attr @func.drop_scope "drop"
  attr @name "pop", "definition"
  attr @func.call "pop" = "()", "pop-scope"
  attr @params.before_scope "jump-to"
  attr @func.return_value "endpoint"
  let @func::function_returns = @func.return_value

  ; Prevent functions defined inside of method bodies from being treated like methods
  let @body::class_self_scope = nil
  let @body::class_member_attr_scope = nil
}

;;
;; BEGIN BIG GNARLY DISJUNCTION
;;
;; The following pair of rules is intended to capture the following behavior:
;;
;; If a function definition is used to define a method, by being inside a class
;; definition, then we make its syntax type `method`. Otherwise, we make it's
;; syntax type `function`. Unfortunately, because of the limitations on negation
;; and binding in tree sitter queries, we cannot negate `class_definition` or
;; similar things directly. Instead, we have to manually push the negation down
;; to form the finite disjunction it corresponds to.
;;

[
  (class_definition (block (decorated_definition (function_definition name: (_)@name))))
  (class_definition (block (function_definition name: (_)@name)))
]
{
  attr @name "syntax_type" = "method"
}

[
  (module (decorated_definition (function_definition name: (_)@name)))
  (module (function_definition name: (_)@name))

  (if_statement (block (decorated_definition (function_definition name: (_)@name))))
  (if_statement (block (function_definition name: (_)@name)))

  (elif_clause (block (decorated_definition (function_definition name: (_)@name))))
  (elif_clause (block (function_definition name: (_)@name)))

  (else_clause (block (decorated_definition (function_definition name: (_)@name))))
  (else_clause (block (function_definition name: (_)@name)))

  (case_clause (block (decorated_definition (function_definition name: (_)@name))))
  (case_clause (block (function_definition name: (_)@name)))

  (for_statement (block (decorated_definition (function_definition name: (_)@name))))
  (for_statement (block (function_definition name: (_)@name)))

  (while_statement (block (decorated_definition (function_definition name: (_)@name))))
  (while_statement (block (function_definition name: (_)@name)))

  (try_statement (block (decorated_definition (function_definition name: (_)@name))))
  (try_statement (block (function_definition name: (_)@name)))

  (except_clause (block (decorated_definition (function_definition name: (_)@name))))
  (except_clause (block (function_definition name: (_)@name)))

  (finally_clause (block (decorated_definition (function_definition name: (_)@name))))
  (finally_clause (block (function_definition name: (_)@name)))

  (with_statement (block (decorated_definition (function_definition name: (_)@name))))
  (with_statement (block (function_definition name: (_)@name)))

  (function_definition (block (decorated_definition (function_definition name: (_)@name))))
  (function_definition (block (function_definition name: (_)@name)))
]
{
  attr @name "syntax_type" = "function"
}

;;
;; END BIG GNARLY DISJUNCTION
;;

(function_definition
  parameters: (parameters
    . (identifier) @param)
  body: (block) @body)
{
  edge @param.input -> @param::class_self_scope
  edge @param::class_member_attr_scope -> @param.output
  edge @param.output -> @body.after_scope
  attr @param.output "push"
}

(parameter/identifier) @param
{
  attr @param.input "definition", "pop"
  attr @param.param_name "push"
  edge @param.input -> @param.param_index
  edge @param.input -> @param.param_name
}

[
  (parameter/default_parameter
    name: (identifier) @name
    value: (_) @value) @param
  (parameter/typed_default_parameter
    name: (_) @name
    value: (_) @value) @param
]
{
  attr @name "definition", "pop"
  attr @param.param_name "push" = @name
  edge @name -> @param.param_name
  edge @name -> @param.param_index
  edge @param.input -> @name
  edge @name -> @value.output
}

[
  (parameter/typed_parameter
    . (_) @name) @param
  (parameter/list_splat_pattern
    (_) @name) @param
  (parameter/dictionary_splat_pattern
    (_) @name) @param
]
{
  attr @name "definition", "pop"
  attr @param.param_name "push" = @name
  edge @name -> @param.param_name
  edge @name -> @param.param_index
  edge @param.input -> @name
}

[
  (pattern_list (_) @pattern)
  (tuple_pattern (_) @pattern)
] @list
{
  let statement_scope = @list::local_scope
  let @pattern::local_scope = @pattern.pattern_before_scope
  edge statement_scope -> @pattern::local_scope, "precedence" = (+ 1 (child-index @pattern))

  edge @pattern.pattern_index -> @list.input
  edge @pattern.input -> @pattern.pattern_index
  attr @pattern.pattern_index "push" = (child-index @pattern)
}

(parameters
  (_) @param) @params
{
  attr @param.param_index "push" = (child-index @param)
  edge @param.param_index -> @params.before_scope
  edge @params.after_scope -> @param.input
  edge @param.param_name -> @params.before_scope
}

(return_statement (_) @expr) @stmt
{
  edge @stmt::function_returns -> @expr.output
}

(class_definition
  name: (identifier) @name) @class
{
  attr @name "definiens" = @class
  attr @name "syntax_type" = "class"
  edge @class.parent_scope -> @class::class_parent_scope
  edge @class.parent_scope -> @class::local_scope
  edge @class.after_scope -> @name
  edge @name -> @class.call
  edge @name -> @class.dot
  edge @class.dot -> @class.members
  edge @class.call -> @class.call_drop
  edge @class.call_drop -> @class.self_scope
  edge @class.self_scope -> @class.super_scope
  edge @class.self_scope -> @class.self_dot
  edge @class.self_dot -> @class.members
  edge @class.members -> @class.member_attrs
  attr @class.call "pop" = "()", "pop-scope"
  attr @class.call_drop "drop"
  attr @class.dot "pop" = "."
  attr @class.self_dot "pop" = "."
  attr @name "pop", "definition"
  attr @class.member_attrs "push" = "."
  attr @class.self_scope "endpoint"
  let @class::super_scope = @class.super_scope
  let @class::class_parent_scope = @class.parent_scope
  let @class::class_self_scope = @class.call_drop
  let @class::class_member_attr_scope = @class.member_attrs
}

(class_definition
  body: (block
    (_) @last_stmt .) @body) @class
{
  edge @class.members -> @last_stmt.after_scope
}

(class_definition
  superclasses: (argument_list
    (_) @superclass)) @class
{
  edge @class.super_scope -> @superclass.output
}

(decorated_definition
  definition: (_) @def) @stmt
{
  edge @def.before_scope -> @stmt.before_scope
  edge @stmt.after_scope -> @def.after_scope
}

(case_clause
  pattern: (_) @pattern
  consequence: (_) @consequence) @clause
{
  edge @consequence.before_scope -> @pattern.new_bindings
  edge @consequence.before_scope -> @clause.before_scope
  edge @clause.after_scope -> @consequence.after_scope
}

;-------------
; Expressions
;-------------

(call
  function: (_) @fn
  arguments: (argument_list) @args) @call
{
  edge @call.output -> @call.output_args
  edge @call.output_args -> @fn.output
  attr @call.output_args "push" = "()", "push-scope" = @args
}

(call
  function: (attribute
    object: (_) @receiver)
  arguments: (argument_list
    (expression) @arg) @args)
{
  edge @args -> @arg.arg_index
  edge @receiver -> @receiver.arg_index

  attr @receiver.arg_index "pop" = "0"
  edge @receiver.arg_index -> @receiver.output

  attr @arg.arg_index "pop" = (+ 1 (child-index @arg))
  edge @arg.arg_index -> @arg.output
}

(call
  arguments: (argument_list
    (keyword_argument
      name: (identifier) @name
      value: (_) @val) @arg) @args) @call
{
  edge @args -> @arg.arg_name
  attr @arg.arg_name "pop" = @name
  edge @arg.arg_name -> @val.output
}

(argument_list
  (expression) @arg) @args
{
  edge @args -> @arg.arg_index
  attr @arg.arg_index "pop" = (child-index @arg)
  edge @arg.arg_index -> @arg.output
}

(
  (call
    function: (identifier) @fn-name) @call
  (#eq? @fn-name "super")
)
{
  edge @call.output -> @call::super_scope
}

[
  (tuple (_) @element)
  (expression_list (_) @element)
] @tuple
{
  edge @tuple.output -> @element.el_index
  attr @element.el_index "pop" = (child-index @element)
  edge @element.el_index -> @element.output

  edge @tuple.new_bindings -> @element.new_bindings
}

(attribute
  object: (_) @object
  attribute: (identifier) @name) @expr
{
  edge @expr.output -> @name.output
  edge @name.output -> @expr.output_dot
  edge @expr.output_dot -> @object.output
  edge @object.input -> @expr.input_dot
  edge @expr.input_dot -> @name.input
  edge @name.input -> @expr.input
  attr @expr.output_dot "push" = "."
  attr @expr.input_dot "pop" = "."
  attr @name.input "pop"
  attr @name.output "push"
}

(pattern/attribute
  attribute: (identifier) @name)
{
  attr @name.input "definition"
}

(primary_expression/attribute
  attribute: (identifier) @name)
{
  attr @name.output "reference"
}

(primary_expression/identifier) @id
{
  edge @id.output -> @id::local_scope
  edge @id.output -> @id::class_parent_scope
  edge @id::local_scope -> @id.input
  attr @id.input "pop"
  attr @id.output "push", "reference"

  attr @id.new_binding_pop "pop", "definition"
  edge @id.new_bindings -> @id.new_binding_pop
}

(pattern/identifier) @id
{
  edge @id.output -> @id::local_scope
  edge @id.output -> @id::class_parent_scope
  edge @id::local_scope -> @id.input, "precedence" = 1
  attr @id.input "pop", "definition"
  attr @id.output "push"

  attr @id.new_binding_pop "pop", "definition"
  edge @id.new_bindings -> @id.new_binding_pop
}

(as_pattern
  (expression) @value
  alias: (as_pattern_target (primary_expression/identifier) @id)) @as_pattern
{
  edge @id.output -> @id::local_scope
  edge @id.output -> @id::class_parent_scope
  edge @id::local_scope -> @id.input, "precedence" = 1
  attr @id.input "pop", "definition"
  attr @id.output "push"

  edge @as_pattern.new_bindings -> @value.new_bindings
  edge @as_pattern.new_bindings -> @id.new_bindings
}

(list) @list
{
  edge @list.output -> @list.called
  edge @list.called -> @list::global_dot
  attr @list.called "push" = "list"
}

(list (_) @el) @list
{
  edge @list.new_bindings -> @el.new_bindings
}

(dictionary (pair) @pair) @dict
{
  edge @dict.new_bindings -> @pair.new_bindings
}

(pair
  value: (_) @value) @pair
{
  edge @pair.new_bindings -> @value.new_bindings
}

(set (_) @el) @set
{
  edge @set.new_bindings -> @el.new_bindings
}

(list_splat (_) @splatted) @splat
{
attr @splat.new_bindings_pop "pop" = @splatted, "definition"
edge @splat.new_bindings -> @splat.new_bindings_pop
}

(binary_operator
  (_) @left
  (_) @right) @binop
{
  edge @binop.new_bindings -> @left.new_bindings
  edge @binop.new_bindings -> @right.new_bindings
}

(case_pattern (_) @expr) @pat
{
  edge @pat.new_bindings -> @expr.new_bindings
}
