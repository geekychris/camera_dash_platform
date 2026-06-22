import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Background,
  Connection,
  Controls,
  Edge,
  Node,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  EdgeChange,
  NodeChange,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, NodeDescriptor, PipelineDef } from "../api/client";
import NodePalette from "./NodePalette";
import PropertiesPanel from "./PropertiesPanel";
import PipelineNode from "./nodes/PipelineNode";
import RecipesModal from "./RecipesModal";
import { describeGraph, layoutGraph, renderInlineMarkdown } from "./graphUtils";
import type { RecipeEdge, RecipeNode } from "./recipes";

const nodeTypes = { pipeline: PipelineNode };

export default function PipelineEditor() {
  return (
    <ReactFlowProvider>
      <EditorBody />
    </ReactFlowProvider>
  );
}

function EditorBody() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<NodeDescriptor[]>([]);
  const [pipelines, setPipelines] = useState<PipelineDef[]>([]);
  const [pipelineId, setPipelineId] = useState<string>(id || newId());
  const [pipelineName, setPipelineName] = useState<string>(id || "New pipeline");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [recipesOpen, setRecipesOpen] = useState(false);
  const rf = useReactFlow();
  const idCounter = useRef(0);

  useEffect(() => {
    api.catalog().then((r) => setCatalog(r.nodes));
    api.listPipelines().then(setPipelines);
  }, []);

  useEffect(() => {
    // Defer until the catalog is loaded, otherwise nodes mount without their
    // descriptor (= no input/output handles), and React Flow rejects edges
    // pointing at non-existent handles.
    if (!id || catalog.length === 0) return;
    api.getPipeline(id).then((p) => {
      setPipelineId(p.id);
      setPipelineName(p.name);
      const desc = (t: string) => catalog.find((c) => c.type_id === t);
      setNodes(
        p.definition.nodes.map((n) => ({
          id: n.id,
          type: "pipeline",
          position: n.position ?? { x: 100, y: 100 },
          data: { type: n.type, config: n.config, descriptor: desc(n.type) },
        })),
      );
      setEdges(
        p.definition.edges.map((e, i) => {
          const [fn, fp] = e.from.split(".", 2);
          const [tn, tp] = e.to.split(".", 2);
          return { id: `e${i}`, source: fn, sourceHandle: fp, target: tn, targetHandle: tp };
        }),
      );
    });
  }, [id, catalog]);

  const onNodesChange = useCallback((c: NodeChange[]) => setNodes((n) => applyNodeChanges(c, n)), []);
  const onEdgesChange = useCallback((c: EdgeChange[]) => setEdges((e) => applyEdgeChanges(c, e)), []);
  const onConnect = useCallback((c: Connection) => setEdges((e) => addEdge({ ...c, id: `e${Date.now()}` }, e)), []);

  function newNodeId(typeId: string) {
    idCounter.current += 1;
    return `${typeId.replace(/[^a-z0-9]/g, "_")}_${idCounter.current}`;
  }

  function addFromPalette(desc: NodeDescriptor) {
    const id = newNodeId(desc.type_id);
    setNodes((n) => [
      ...n,
      {
        id,
        type: "pipeline",
        position: rf.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 }),
        data: { type: desc.type_id, config: {}, descriptor: desc },
      },
    ]);
  }

  function updateConfig(nodeId: string, config: Record<string, unknown>) {
    setNodes((n) => n.map((node) => (node.id === nodeId ? { ...node, data: { ...node.data, config } } : node)));
  }

  function insertRecipe(chunk: { nodes: RecipeNode[]; edges: RecipeEdge[] }) {
    const desc = (t: string) => catalog.find((c) => c.type_id === t);
    const centre = rf.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
    // Lay the recipe out in a vertical strip near the viewport centre. Auto-
    // layout runs after to align it with the existing graph horizontally.
    const newNodes: Node[] = chunk.nodes.map((n, i) => ({
      id: n.id,
      type: "pipeline",
      position: { x: centre.x, y: centre.y + i * 90 },
      data: { type: n.type, config: n.config, descriptor: desc(n.type) },
    }));
    const newEdges: Edge[] = chunk.edges.map((e, i) => {
      const [fn, fp] = e.from.split(".", 2);
      const [tn, tp] = e.to.split(".", 2);
      return { id: `e-${Date.now()}-${i}`, source: fn, sourceHandle: fp, target: tn, targetHandle: tp };
    });
    setNodes((n) => [...n, ...newNodes]);
    setEdges((e) => [...e, ...newEdges]);
    // Defer to next tick so React applies the state, then re-flow + fit.
    setTimeout(() => {
      setNodes((n) => layoutGraph(n, [...edges, ...newEdges]));
      setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 0);
    }, 0);
  }

  // Cursor-key nudge for the selected node. Shift = 10px, otherwise 1px.
  // Bypasses while a text field has focus so typing in the id/name inputs
  // or the properties panel doesn't move nodes.
  useEffect(() => {
    if (!selectedId) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      const step = e.shiftKey ? 10 : 1;
      const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
      const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
      if (dx === 0 && dy === 0) return;
      e.preventDefault();
      setNodes((nds) =>
        nds.map((n) =>
          n.id === selectedId
            ? { ...n, position: { x: n.position.x + dx, y: n.position.y + dy } }
            : n,
        ),
      );
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedId]);

  const selected = useMemo(() => nodes.find((n) => n.id === selectedId) || null, [nodes, selectedId]);
  const description = useMemo(() => describeGraph(nodes, edges), [nodes, edges]);

  function autoLayout() {
    setNodes((n) => layoutGraph(n, edges));
    setTimeout(() => rf.fitView({ padding: 0.2, duration: 300 }), 0);
  }

  async function save() {
    const def = {
      id: pipelineId,
      name: pipelineName,
      nodes: nodes.map((n) => ({
        id: n.id,
        type: (n.data as { type: string }).type,
        config: (n.data as { config: Record<string, unknown> }).config,
        position: { x: n.position.x, y: n.position.y },
      })),
      edges: edges.map((e) => ({
        from: `${e.source}.${e.sourceHandle ?? "out"}`,
        to: `${e.target}.${e.targetHandle ?? "in"}`,
      })),
    };
    try {
      await api.savePipeline({ id: pipelineId, name: pipelineName, definition: def, enabled: false });
      alert("Saved");
      setPipelines(await api.listPipelines());
    } catch (e) {
      alert(String(e));
    }
  }

  async function start() {
    try {
      await api.startPipeline(pipelineId);
      alert("Started");
    } catch (e) {
      alert(String(e));
    }
  }

  async function stop() {
    try {
      await api.stopPipeline(pipelineId);
      alert("Stopped");
    } catch (e) {
      alert(String(e));
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex h-full w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
        <div className="shrink-0 border-b border-slate-800 px-3 py-2 text-sm font-semibold">Pipelines</div>
        <div className="max-h-48 shrink-0 overflow-y-auto p-2 text-sm">
          <button
            className="mb-2 w-full rounded bg-blue-600 px-2 py-1 hover:bg-blue-500"
            onClick={() => navigate("/editor")}
          >
            + New
          </button>
          {pipelines.map((p) => (
            <button
              key={p.id}
              onClick={() => navigate(`/editor/${p.id}`)}
              className={`mb-1 block w-full truncate rounded px-2 py-1 text-left hover:bg-slate-800 ${
                p.id === pipelineId ? "bg-slate-800" : ""
              }`}
            >
              {p.name || p.id}
              {p.enabled && <span className="ml-2 text-xs text-green-400">●</span>}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto border-t border-slate-800">
          <NodePalette catalog={catalog} onAdd={addFromPalette} />
        </div>
      </div>

      <div className="flex flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2 text-sm">
          <input
            className="rounded bg-slate-950 px-2 py-1"
            value={pipelineId}
            onChange={(e) => setPipelineId(e.target.value)}
            placeholder="id"
          />
          <input
            className="rounded bg-slate-950 px-2 py-1"
            value={pipelineName}
            onChange={(e) => setPipelineName(e.target.value)}
            placeholder="name"
          />
          <button className="rounded bg-blue-600 px-3 py-1 hover:bg-blue-500" onClick={save}>
            Save
          </button>
          <button className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800" onClick={start}>
            Start
          </button>
          <button className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800" onClick={stop}>
            Stop
          </button>
          <button
            className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800"
            onClick={autoLayout}
            title="Auto-arrange nodes left-to-right by graph depth"
          >
            Layout
          </button>
          <button
            className="rounded border border-emerald-700 px-3 py-1 text-emerald-300 hover:bg-emerald-900/40"
            onClick={() => setRecipesOpen(true)}
            title="Insert a pre-wired sub-graph (detect → notify, audio alert, fall detection, etc.)"
          >
            + Recipe
          </button>
        </div>
        {nodes.length > 0 && (
          <div className="border-b border-slate-800 bg-slate-950 px-3 py-2 text-xs leading-relaxed text-slate-300">
            {renderInlineMarkdown(description)}
          </div>
        )}
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            fitView
          >
            <Background gap={16} />
            <Controls />
          </ReactFlow>
        </div>
      </div>

      <div className="w-80 shrink-0 border-l border-slate-800 bg-slate-950">
        <PropertiesPanel
          node={selected}
          onChange={(cfg) => selected && updateConfig(selected.id, cfg)}
        />
      </div>

      <RecipesModal open={recipesOpen} onClose={() => setRecipesOpen(false)} onInsert={insertRecipe} />
    </div>
  );
}

function newId(): string {
  return `pipeline_${Math.random().toString(36).slice(2, 8)}`;
}
