import { useEffect, useRef } from "react";
import {
  AmbientLight,
  BufferAttribute,
  BufferGeometry,
  Color,
  GridHelper,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Scene,
  WebGLRenderer,
} from "three";
import { CameraInfo, depthSubscribe } from "../api/client";

/**
 * 3D point-cloud tile for any depth-capable camera. Subscribes to the
 * existing /api/depth/{cam} WebSocket, back-projects each uint16 mm sample
 * through pinhole intrinsics into XYZ, and renders the result as a
 * Three.js point cloud with an orbiting camera + a floor grid.
 *
 * Intrinsics default to Kinect v1 factory cal; can be overridden per
 * camera if/when other depth devices come online. Same numbers
 * sink.point_cloud uses on the backend.
 *
 * Auto-stretches near/far each frame for color contrast so a scene of
 * 1–3 m doesn't render as a tiny band of barely-distinguishable hues.
 */
export default function PointCloudTile({ camera }: { camera: CameraInfo }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<{
    points?: Points;
    geometry?: BufferGeometry;
    renderer?: WebGLRenderer;
    scene?: Scene;
    cam?: PerspectiveCamera;
    raf?: number;
    drag?: { x: number; y: number; az: number; el: number };
    orbit: { az: number; el: number; r: number };
  }>({ orbit: { az: Math.PI / 4, el: Math.PI / 6, r: 3.0 } });

  useEffect(() => {
    const host = mountRef.current;
    if (!host) return;
    const state = stateRef.current;

    const scene = new Scene();
    scene.background = new Color(0x0b1220);
    const cam = new PerspectiveCamera(60, host.clientWidth / host.clientHeight, 0.05, 50);
    updateCamera(cam, state.orbit);

    const grid = new GridHelper(6, 12, 0x334155, 0x1e293b);
    grid.position.y = -1.2; // approximate floor
    scene.add(grid);
    scene.add(new AmbientLight(0xffffff, 1));

    const geometry = new BufferGeometry();
    const material = new PointsMaterial({ size: 0.012, vertexColors: true });
    const points = new Points(geometry, material);
    scene.add(points);

    const renderer = new WebGLRenderer({ antialias: false, powerPreference: "low-power" });
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    host.appendChild(renderer.domElement);

    state.scene = scene;
    state.cam = cam;
    state.geometry = geometry;
    state.points = points;
    state.renderer = renderer;

    function loop() {
      renderer.render(scene, cam);
      state.raf = requestAnimationFrame(loop);
    }
    state.raf = requestAnimationFrame(loop);

    const onResize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      cam.aspect = w / h;
      cam.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(host);

    // --- mouse orbit ---
    const canvas = renderer.domElement;
    canvas.style.cursor = "grab";
    const onDown = (e: MouseEvent) => {
      state.drag = { x: e.clientX, y: e.clientY, az: state.orbit.az, el: state.orbit.el };
      canvas.style.cursor = "grabbing";
    };
    const onMove = (e: MouseEvent) => {
      if (!state.drag) return;
      const dx = e.clientX - state.drag.x;
      const dy = e.clientY - state.drag.y;
      state.orbit.az = state.drag.az + dx * 0.01;
      state.orbit.el = clamp(state.drag.el + dy * 0.01, -Math.PI / 2 + 0.1, Math.PI / 2 - 0.1);
      updateCamera(cam, state.orbit);
    };
    const onUp = () => {
      state.drag = undefined;
      canvas.style.cursor = "grab";
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      state.orbit.r = clamp(state.orbit.r * (e.deltaY > 0 ? 1.1 : 0.9), 0.3, 12);
      updateCamera(cam, state.orbit);
    };
    canvas.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    // --- depth WS subscription ---
    // Strip the `:3d` layout-key suffix the dashboard appends to keep this
    // tile's layout box distinct from the RGB tile's; the WS endpoint
    // /api/depth/{cam} uses the real camera id.
    const cameraId = camera.id.endsWith(":3d") ? camera.id.slice(0, -3) : camera.id;
    const unsubscribe = depthSubscribe(cameraId, (w, h, data) => {
      if (!state.geometry) return;
      const { positions, colors } = backproject(w, h, data);
      state.geometry.setAttribute("position", new BufferAttribute(positions, 3));
      state.geometry.setAttribute("color", new BufferAttribute(colors, 3));
      state.geometry.attributes.position.needsUpdate = true;
      state.geometry.attributes.color.needsUpdate = true;
      state.geometry.computeBoundingSphere();
    });

    return () => {
      unsubscribe();
      if (state.raf !== undefined) cancelAnimationFrame(state.raf);
      ro.disconnect();
      canvas.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("wheel", onWheel);
      host.removeChild(renderer.domElement);
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    };
  }, [camera.id]);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="drag-handle flex h-7 shrink-0 cursor-move items-center justify-between border-b border-slate-800 bg-slate-950 px-3 text-xs select-none">
        <span className="flex min-w-0 items-center gap-2 truncate">
          <span className="rounded bg-cyan-700 px-1.5 py-px text-[10px] uppercase tracking-wide text-cyan-100">
            3d
          </span>
          <span className="truncate">{camera.label || camera.id} — point cloud</span>
        </span>
        <span className="ml-2 text-slate-500">drag to orbit · wheel to zoom</span>
      </div>
      <div ref={mountRef} className="relative min-h-0 flex-1 bg-black" />
    </div>
  );
}

// --- Kinect v1 intrinsics (matches sink.point_cloud defaults) ---
const FX = 594.21;
const FY = 591.04;
const CX = 339.5;
const CY = 242.7;
const MAX_MM = 6000;

function backproject(
  w: number,
  h: number,
  data: Uint16Array,
): { positions: Float32Array; colors: Float32Array } {
  // The server downsamples depth to ~320 wide before sending; that's already
  // a ~5× reduction from native, so we don't down-sample further. ~38k points
  // at most — Three.js with vertex colors handles that fine on any GPU.
  const N = w * h;
  const tmpX = new Float32Array(N);
  const tmpY = new Float32Array(N);
  const tmpZ = new Float32Array(N);
  const scaleX = 640 / w; // we want the intrinsics in the original native px-grid
  const scaleY = 480 / h;
  let valid = 0;
  let zmin = Infinity, zmax = -Infinity;
  for (let v = 0; v < h; v++) {
    for (let u = 0; u < w; u++) {
      const mm = data[v * w + u];
      if (mm === 0 || mm > MAX_MM) continue;
      const z = mm / 1000; // metres
      const x = ((u * scaleX) - CX) * z / FX;
      const y = ((v * scaleY) - CY) * z / FY;
      tmpX[valid] = x;
      tmpY[valid] = -y; // Three.js y-up vs image y-down
      tmpZ[valid] = -z; // camera looks down -Z by default
      if (z < zmin) zmin = z;
      if (z > zmax) zmax = z;
      valid++;
    }
  }
  const positions = new Float32Array(valid * 3);
  const colors = new Float32Array(valid * 3);
  const span = Math.max(0.01, zmax - zmin);
  for (let i = 0; i < valid; i++) {
    positions[i * 3 + 0] = tmpX[i];
    positions[i * 3 + 1] = tmpY[i];
    positions[i * 3 + 2] = tmpZ[i];
    // Map z to a turbo-ish color ramp: near = warm, far = cool.
    const t = ((-tmpZ[i]) - zmin) / span; // 0..1 from near to far
    const [r, g, b] = turbo(t);
    colors[i * 3 + 0] = r;
    colors[i * 3 + 1] = g;
    colors[i * 3 + 2] = b;
  }
  return { positions, colors };
}

// Cheap polynomial approximation of OpenCV's TURBO palette; good enough for
// the visual gradient we want without bundling an LUT.
function turbo(t: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, t));
  const r = clamp(34.61 + x * (1172.33 - x * (10793.56 - x * (33300.12 - x * (38394.49 - x * 14825.05)))), 0, 255) / 255;
  const g = clamp(23.31 + x * (557.33 + x * (1225.33 - x * (3574.96 - x * (1073.77 + x * 707.56)))), 0, 255) / 255;
  const b = clamp(27.2 + x * (3211.1 - x * (15327.97 - x * (27814 - x * (22569.18 - x * 6838.66)))), 0, 255) / 255;
  return [r, g, b];
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function updateCamera(cam: PerspectiveCamera, orbit: { az: number; el: number; r: number }) {
  const x = orbit.r * Math.cos(orbit.el) * Math.sin(orbit.az);
  const y = orbit.r * Math.sin(orbit.el);
  const z = orbit.r * Math.cos(orbit.el) * Math.cos(orbit.az);
  cam.position.set(x, y, z);
  cam.lookAt(0, 0, -1.5);
}
