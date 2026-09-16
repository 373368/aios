import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * 星空背景：知识库力导向图（全屏 canvas，固定在最底层）。
 * 复用驾驶舱 vendored 的 3d-force-graph（UMD，全局 ForceGraph3D）+ 完整 three（npm，ESM import）。
 *
 * 氛围仿 agents-knowledge-base 原版：暗星层 + 节点光晕（CanvasTexture + Additive）+ 链接流动粒子。
 *
 * 性能关键（原版模式）：节点对象在 nodeThreeObject 一次性创建并缓存引用（n.__glow/n.__core），
 * 之后呼吸/闪烁只直接改已存在对象的 scale/color 属性，绝不 graph.refresh()/重建（2356 节点重建=PPT 卡顿）。
 */
export function StarfieldBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let graph: any;
    let disposed = false;
    let pulseTimer: ReturnType<typeof setInterval> | undefined;
    let hovered: any = null;

    /** 原版 glowTexture：256x256 径向渐变，中心亮 → 边缘透明（节点光晕） */
    const glowTexCache = new Map<string, THREE.Texture>();
    function glowTexture(color: string) {
      const cached = glowTexCache.get(color);
      if (cached) return cached;
      const c = document.createElement("canvas");
      c.width = c.height = 256;
      const ctx = c.getContext("2d")!;
      const g = ctx.createRadialGradient(128, 128, 4, 128, 128, 128);
      g.addColorStop(0, color + "cc");
      g.addColorStop(0.3, color + "55");
      g.addColorStop(0.65, color + "11");
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 256, 256);
      const tex = new THREE.CanvasTexture(c);
      glowTexCache.set(color, tex);
      return tex;
    }

    /** 创建单个节点对象（Group = 光晕 Sprite + 核心小球），缓存引用到 node 上 */
    function makeNodeObj(node: any) {
      const r = node.hub ? 4 : node.kind === "tag" ? 2.8 : 1.6;
      const group = new THREE.Group();
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: glowTexture(node.color || "#04d9ff"),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      const gs = Math.min(r, 5.5) * (node.kind === "note" ? 4.6 : 3.4);
      glow.scale.set(gs, gs, 1);
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(r * 0.55, 12, 12),
        new THREE.MeshBasicMaterial({ color: node.color || "#04d9ff", transparent: true }),
      );
      group.add(glow, core);
      // 缓存引用：之后只改属性，不重建
      (node as any).__glow = glow;
      (node as any).__core = core;
      (node as any).__gs = gs;
      return group;
    }

    async function init() {
      const FG = (window as any).ForceGraph3D;
      if (!FG) return; // vendor 脚本未加载（如开发环境）

      graph = FG({ controlType: "orbit" })(container)
        .backgroundColor("#020208")
        .showNavInfo(false)
        .nodeColor((n: any) => n.color || "#04d9ff")
        .nodeVal((n: any) => (n.hub ? 4 : n.kind === "tag" ? 2.8 : 1.6))
        .linkColor(() => "#5a7fb4")
        .linkWidth(1.0)
        .linkOpacity(0.5)
        // 链接流动粒子（原版 synthwave 感）
        .linkDirectionalParticleWidth(() => 1.3)
        .linkDirectionalParticleSpeed(() => 0.006)
        .linkDirectionalParticles((l: any) => (l.hot ? 6 : 2))
        .linkDirectionalParticleColor(() => "#ffffff")
        // 节点对象：一次性创建（性能关键，勿重建）
        .nodeThreeObject((n: any) => makeNodeObj(n))
        .onNodeHover((n: any) => {
          document.body.style.cursor = n ? "pointer" : "default";
          // 直接改 hover 节点光晕 scale（只动一个对象，零重建）
          if (n && n.__glow) {
            const s = n.__gs * 1.8;
            n.__glow.scale.set(s, s, 1);
          }
          // 恢复上一个 hover 节点
          if (hovered && hovered !== n && hovered.__glow) {
            const s0 = hovered.__gs;
            hovered.__glow.scale.set(s0, s0, 1);
          }
          hovered = n;
        });

      graph.d3Force("charge")?.strength(-30);
      graph.d3Force("center")?.strength(0.02);
      graph.controls().autoRotate = true;
      graph.controls().autoRotateSpeed = 0.4;

      // 暗星层（原版 addStars：850 颗暗紫星）
      const N = 850;
      const pos = new Float32Array(N * 3);
      for (let i = 0; i < N * 3; i++) pos[i] = (Math.random() - 0.5) * 4200;
      const starsGeo = new THREE.BufferGeometry();
      starsGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      const stars = new THREE.Points(starsGeo, new THREE.PointsMaterial({
        color: 0x2b2547,
        size: 0.85,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.16,
      }));
      graph.scene().add(stars);

      try {
        const resp = await fetch("/graph-data");
        if (!resp.ok) throw new Error(`graph-data ${resp.status}`);
        const data = await resp.json();
        if (!disposed) graph.graphData(data);
      } catch {
        if (!disposed) graph.graphData({ nodes: [], links: [] });
      }

      // 整体占比放大：zoomToFit 边距 70 → 12，星空撑满视口（1200ms 缓动=放大动画），节点尺寸不变
      if (!disposed) setTimeout(() => graph?.zoomToFit?.(1200, 12), 1600);

      // 星辰呼吸：随机 3 节点放大光晕，其余恢复（只改属性，零重建）
      let nodes: any[] = [];
      let lastPicks = new Set<any>();
      pulseTimer = setInterval(() => {
        if (!graph || disposed) return;
        if (nodes.length === 0) nodes = (graph.graphData() as any)?.nodes ?? [];
        if (nodes.length === 0) return;
        const picks = new Set(
          nodes.filter((n: any) => !n.hub && n.__glow).sort(() => Math.random() - 0.5).slice(0, 3),
        );
        // 恢复上一轮选中的
        lastPicks.forEach((n: any) => {
          if (!picks.has(n) && n.__glow) {
            const s = n.__gs;
            n.__glow.scale.set(s, s, 1);
          }
        });
        // 放大本轮选中的
        picks.forEach((n: any) => {
          if (n.__glow) {
            const s = n.__gs * 1.9;
            n.__glow.scale.set(s, s, 1);
          }
        });
        lastPicks = picks;
      }, 900);
    }

    init();

    // 窗口/容器尺寸变化时同步渲染尺寸（vendored 3d-force-graph 不自动监听 resize，否则全屏后星空偏移）
    const resizeObserver = new ResizeObserver(() => {
      if (!graph || disposed) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w > 0 && h > 0) graph.width(w).height(h);
    });
    resizeObserver.observe(container);

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      if (pulseTimer) clearInterval(pulseTimer);
      try { graph?.graphData?.({ nodes: [], links: [] }); graph?.pauseAnimation?.(); } catch { /* ignore */ }
    };
  }, []);

  return <div ref={containerRef} className="aios-starfield" aria-hidden="true" />;
}