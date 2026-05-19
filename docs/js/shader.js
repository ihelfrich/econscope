/*
 * ECONSCOPE — bespoke shader background
 *
 * A single, very-slow-drifting flow-field shader at low opacity behind the hero.
 * Suggested by the research agent as the only motion the page should carry —
 * "absent, or one bespoke shader, not a particle preset."
 *
 * The shader produces a low-density worley/voronoi-noise field in two warm
 * oxblood / ink tones, drifting very slowly. Mask is applied via CSS so the
 * effect concentrates in the upper-left of the viewport and fades to nothing
 * over the rest of the page.
 *
 * No dependencies. ~140 lines including shader source.
 */

(function () {
  'use strict';

  // Respect reduced-motion users; show a static frame, no animation.
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const canvas = document.getElementById('shader-canvas');
  if (!canvas) return;

  const gl = canvas.getContext('webgl', { antialias: true, premultipliedAlpha: true });
  if (!gl) {
    // Graceful: do nothing. The grid + grain background still carries the page.
    canvas.style.display = 'none';
    return;
  }

  // Fit canvas to viewport with devicePixelRatio capped to 2 (perf safety on
  // retina screens — shader at 4x is heavy and not visually distinguishable
  // from 2x at the opacity level we're rendering at).
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  function resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    gl.viewport(0, 0, canvas.width, canvas.height);
  }
  resize();
  window.addEventListener('resize', resize);

  // ── Vertex shader (full-screen triangle) ────────────────────────────────
  const vsSource = `
    attribute vec2 a_pos;
    void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
  `;

  // ── Fragment shader: two-octave worley + flow field ─────────────────────
  // The result is an organic, slow-drifting field of cell-like shapes in two
  // closely-related warm tones. The cells are LARGE relative to the canvas
  // (only 3–4 cells visible at once) — this is what keeps it from reading as
  // "particle pattern."
  const fsSource = `
    precision highp float;
    uniform vec2  u_res;
    uniform float u_time;

    // Hash function (one of Inigo Quilez's standards)
    vec2 hash2(vec2 p) {
      p = vec2(dot(p, vec2(127.1, 311.7)),
               dot(p, vec2(269.5, 183.3)));
      return -1.0 + 2.0 * fract(sin(p) * 43758.5453);
    }

    // Worley / voronoi distance: returns f1 (distance to nearest cell point)
    float worley(vec2 x) {
      vec2 n = floor(x);
      vec2 f = fract(x);
      float d = 1.0;
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          vec2 g = vec2(float(i), float(j));
          vec2 o = 0.5 + 0.5 * hash2(n + g);
          vec2 r = g + o - f;
          d = min(d, dot(r, r));
        }
      }
      return sqrt(d);
    }

    void main() {
      vec2 uv = gl_FragCoord.xy / u_res.xy;
      // Aspect-correct coordinates so cells don't stretch
      vec2 p = uv * vec2(u_res.x / u_res.y, 1.0) * 2.4;

      // Slow temporal drift — very low frequency
      float t = u_time * 0.018;
      p += vec2(cos(t * 0.7), sin(t * 0.5)) * 0.3;

      // Two octaves of worley, low contribution from second octave
      float w1 = worley(p);
      float w2 = worley(p * 2.3 + 11.7) * 0.35;
      float w = w1 + w2;

      // Color: two warm tones — oxblood and warm-ink, mixed by the field
      vec3 c1 = vec3(0.478, 0.122, 0.169);   // #7a1f2b oxblood
      vec3 c2 = vec3(0.102, 0.102, 0.102);   // #1a1a1a ink
      vec3 c = mix(c1, c2, smoothstep(0.0, 1.4, w));

      // Heavy gamma + vignette toward edges to feel "lit from one direction"
      float vig = 1.0 - smoothstep(0.0, 1.0, length(uv - vec2(0.18, 0.12)) * 0.9);
      c *= mix(0.4, 1.0, vig);

      gl_FragColor = vec4(c, 1.0);
    }
  `;

  function compile(type, source) {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.warn('Shader compile error:', gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  const vs = compile(gl.VERTEX_SHADER, vsSource);
  const fs = compile(gl.FRAGMENT_SHADER, fsSource);
  if (!vs || !fs) { canvas.style.display = 'none'; return; }

  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.warn('Program link error:', gl.getProgramInfoLog(program));
    canvas.style.display = 'none';
    return;
  }
  gl.useProgram(program);

  // Single full-screen quad (two triangles via TRIANGLE_STRIP)
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,   1, -1,   -1, 1,   1, 1,
  ]), gl.STATIC_DRAW);
  const aPos = gl.getAttribLocation(program, 'a_pos');
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

  const uRes  = gl.getUniformLocation(program, 'u_res');
  const uTime = gl.getUniformLocation(program, 'u_time');

  const start = performance.now();
  function frame() {
    const t = (performance.now() - start) / 1000;
    gl.uniform2f(uRes, canvas.width, canvas.height);
    gl.uniform1f(uTime, t);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    if (!reducedMotion) requestAnimationFrame(frame);
  }
  if (reducedMotion) {
    // One frame only, then stop. Effect is static.
    gl.uniform2f(uRes, canvas.width, canvas.height);
    gl.uniform1f(uTime, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  } else {
    requestAnimationFrame(frame);
  }
})();
