/* Strategy map connectors: SVG arrows from cause (source) to effect (target), redrawn on resize. */
(() => {
  const map = document.querySelector('.smap');
  if (!map) return;
  const svg = map.querySelector('svg.links');
  const edges = JSON.parse(map.dataset.edges || '[]');
  const NS = 'http://www.w3.org/2000/svg';

  function draw() {
    svg.querySelectorAll('path.edge').forEach((p) => p.remove());
    const box = map.getBoundingClientRect();
    edges.forEach(({ from, to }, i) => {
      const a = map.querySelector(`[data-node="${from}"]`);
      const b = map.querySelector(`[data-node="${to}"]`);
      if (!a || !b) return;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const ca = { x: ra.left + ra.width / 2 - box.left, y: ra.top - box.top };           // leave from the top of the cause
      const cb = { x: rb.left + rb.width / 2 - box.left, y: rb.bottom - box.top + 2 };    // arrive at the bottom of the effect
      const dy = Math.max(40, Math.abs(ca.y - cb.y) / 2);
      // An edge that skips a perspective would run straight through the nodes in between:
      // bow it sideways (alternating sides) so it passes beside them.
      const skips = Math.abs(ca.x - cb.x) < 60 && Math.abs(ca.y - cb.y) > 140;
      const bow = skips ? (i % 2 ? -1 : 1) * 210 : 0;
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('class', 'edge');
      path.setAttribute('d', `M${ca.x} ${ca.y} C${ca.x + bow} ${ca.y - dy} ${cb.x + bow} ${cb.y + dy} ${cb.x} ${cb.y}`);
      path.setAttribute('marker-end', 'url(#arrow)');
      svg.appendChild(path);
    });
  }
  draw();
  window.addEventListener('resize', draw);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
})();
