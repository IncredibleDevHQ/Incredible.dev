// graph-contract.mjs: the semantics of a diagram, frozen before layout.
//
// A contract names every node (id, label) and every edge (id, from, to, kind, label). Its topology
// hash changes when any label, id, endpoint, direction or kind changes, so a styling revision can pin
// the hash and fail before layout if the meaning moved. After rendering, auditRenderedGraph compares
// what the SVG actually drew against the contract.

import { createHash } from "node:crypto";

const ID_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const EDGE_KINDS = new Set(["association", "flow", "feedback", "return", "human-loop", "self-loop"]);
const MAX_NODES = 48;
const MAX_EDGES = 96;
const MAX_TEXT = 160;
const MAX_SOURCE = 480;

function fail(message) {
  throw new Error(`graph-contract: ${message}`);
}

function array(value, name, max) {
  if (!Array.isArray(value)) fail(`${name} must be an array`);
  if (value.length > max) fail(`${name} exceeds limit ${max}`);
  return value;
}

function text(value, name, { required = true, max = MAX_TEXT } = {}) {
  if (!required && (value === undefined || value === null || value === "")) return "";
  if (typeof value !== "string" || value.trim() === "") fail(`${name} must be non-empty text`);
  const normalized = value.trim();
  if (normalized.length > max) fail(`${name} exceeds ${max} characters`);
  return normalized;
}

function id(value, name) {
  const normalized = text(value, name, { max: 64 });
  if (!ID_PATTERN.test(normalized)) {
    fail(`${name} must match ${ID_PATTERN}`);
  }
  return normalized;
}

function unique(items, name) {
  const seen = new Set();
  for (const item of items) {
    if (seen.has(item.id)) fail(`duplicate ${name} id: ${item.id}`);
    seen.add(item.id);
  }
}

function sortedContract(contract) {
  return {
    version: contract.version,
    nodes: [...contract.nodes]
      .map(({ id: nodeId, label }) => ({ id: nodeId, label }))
      .sort((a, b) => a.id.localeCompare(b.id)),
    edges: [...contract.edges]
      .map(({ id: edgeId, from, to, kind, label }) => ({
        id: edgeId,
        from,
        to,
        kind,
        ...(label ? { label } : {}),
      }))
      .sort((a, b) => a.id.localeCompare(b.id)),
  };
}

export function normalizeGraphContract(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail("contract must be an object");
  }
  if (value.version !== 1) fail("contract.version must be 1");
  const source = text(value.source, "contract.source", { required: false, max: MAX_SOURCE });
  const nodes = array(value.nodes, "contract.nodes", MAX_NODES).map((node, index) => ({
    id: id(node?.id, `contract.nodes[${index}].id`),
    label: text(node?.label, `contract.nodes[${index}].label`),
  }));
  if (nodes.length === 0) fail("contract.nodes must not be empty");
  unique(nodes, "contract node");

  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = array(value.edges, "contract.edges", MAX_EDGES).map((edge, index) => {
    const kind = text(edge?.kind, `contract.edges[${index}].kind`);
    if (!EDGE_KINDS.has(kind)) fail(`contract.edges[${index}].kind is unsupported`);
    const normalized = {
      id: id(edge?.id, `contract.edges[${index}].id`),
      from: id(edge?.from, `contract.edges[${index}].from`),
      to: id(edge?.to, `contract.edges[${index}].to`),
      kind,
      label: text(edge?.label, `contract.edges[${index}].label`, { required: false }),
    };
    if (!nodeIds.has(normalized.from)) {
      fail(`contract edge ${normalized.id} references unknown source: ${normalized.from}`);
    }
    if (!nodeIds.has(normalized.to)) {
      fail(`contract edge ${normalized.id} references unknown target: ${normalized.to}`);
    }
    if (kind === "self-loop" && normalized.from !== normalized.to) {
      fail(`contract edge ${normalized.id} self-loop must target its source`);
    }
    if (kind !== "self-loop" && normalized.from === normalized.to) {
      fail(`contract edge ${normalized.id} must use kind self-loop`);
    }
    return normalized;
  });
  unique(edges, "contract edge");
  return { version: 1, source, nodes, edges };
}

export function graphTopology(contract) {
  const canonical = sortedContract(contract);
  return {
    hash: createHash("sha256").update(JSON.stringify(canonical)).digest("hex"),
    nodes: canonical.nodes,
    edges: canonical.edges,
  };
}

/**
 * Inverse audit: what a renderer actually drew, read back out of its SVG, against the contract. A
 * render that looks right cannot hide a missing, invented or reversed edge.
 * @param {{nodes: string[], edges: {from: string, to: string, directed: boolean}[]}} drawn
 */
export function auditRenderedGraph(drawn, contract) {
  const topology = graphTopology(contract);
  const expectedNodes = new Set(contract.nodes.map((node) => node.id));
  const drawnNodes = new Set(drawn.nodes);
  const missingNodes = [...expectedNodes].filter((nodeId) => !drawnNodes.has(nodeId));
  const extraNodes = [...drawnNodes].filter((nodeId) => !expectedNodes.has(nodeId));
  if (missingNodes.length) fail(`rendered graph is missing nodes: ${missingNodes.join(", ")}`);
  if (extraNodes.length) fail(`rendered graph has nodes the contract does not: ${extraNodes.join(", ")}`);
  const key = (edge) => `${edge.from}${edge.directed ? "->" : "--"}${edge.to}`;
  const want = new Map();
  for (const edge of contract.edges) {
    const k = key({ ...edge, directed: edge.kind !== "association" });
    want.set(k, (want.get(k) || 0) + 1);
  }
  for (const edge of drawn.edges) {
    const k = key(edge);
    if (!want.get(k)) fail(`rendered edge ${k} is not in the contract (missing, invented or reversed)`);
    want.set(k, want.get(k) - 1);
  }
  const missingEdges = [...want].filter(([, count]) => count > 0).map(([k]) => k);
  if (missingEdges.length) fail(`rendered graph is missing edges: ${missingEdges.join(", ")}`);
  return { ok: true, topologyHash: topology.hash, nodeCount: drawnNodes.size, edgeCount: drawn.edges.length };
}
