import * as THREE from '/vendor/three.module.js';

const canvas = document.getElementById('office');
const status = document.getElementById('scene-status');
let renderer, enabled = false, last = 0, yaw = .6, tilt = .65, dragging = false, previousX = 0;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const scene = new THREE.Scene(); scene.background = new THREE.Color('#09111c');
const camera = new THREE.PerspectiveCamera(45, 2, .1, 100);
scene.add(new THREE.AmbientLight(0xc5e5ff, 2));
const light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(2, 8, 4); scene.add(light);
const rooms = [
  ['CEO', 0, -3, '#337d8d'], ['Research', -4, 0, '#305f86'], ['Strategy', 0, 0, '#554884'],
  ['Risk', 4, 0, '#86533e'], ['Execution', -4, 3, '#3c7060'], ['Portfolio', 0, 3, '#45677c'], ['Technology', 4, 3, '#5f587e']
];
function label(text) {
  const image = document.createElement('canvas'); image.width = 256; image.height = 64;
  const ctx = image.getContext('2d'); ctx.fillStyle = '#dce7f5'; ctx.font = '28px sans-serif'; ctx.textAlign = 'center'; ctx.fillText(text, 128, 42);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(image), transparent: true})); sprite.scale.set(2, .5, 1); return sprite;
}
rooms.forEach(([name, x, z, color]) => {
  const floor = new THREE.Mesh(new THREE.BoxGeometry(3.6, .12, 2.6), new THREE.MeshStandardMaterial({color})); floor.position.set(x, 0, z); scene.add(floor);
  const text = label(name); text.position.set(x, .3, z - 1); scene.add(text);
});
const assignments = {ceo:0, market:1, technical:1, news:1, data:1, strategy:2, signal:2, risk:3, execution:4,
  portfolio:5, performance:5, accounting:5, monitor:6, backtest:6, report:6, security:6};
const avatars = new Map(); const offsets = {};
for (const [id, room] of Object.entries(assignments)) {
  const index = offsets[room] || 0; offsets[room] = index + 1;
  const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(.17, .35, 3, 6), new THREE.MeshStandardMaterial({color: '#7d8b9f'}));
  mesh.position.set(rooms[room][1] - .85 + (index % 3) * .85, .48, rooms[room][2] + Math.floor(index / 3) * .7);
  mesh.userData = {id, state: 'Offline', y: .48}; scene.add(mesh); avatars.set(id, mesh);
  const name = label(id); name.scale.set(.85, .21, 1); name.position.copy(mesh.position); name.position.y = 1.12; scene.add(name);
}
const colors = {Idle:'#7d8b9f', Working:'#64dbc1', Thinking:'#b194ff', Waiting:'#d9ad62', Error:'#f47791', Offline:'#3b4554'};
function resize() {
  if (!renderer) return;
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false); camera.aspect = canvas.clientWidth / canvas.clientHeight; camera.updateProjectionMatrix();
}
function render(timestamp) {
  requestAnimationFrame(render);
  if (!enabled || document.hidden || timestamp - last < 1000/30 || !renderer) return;
  last = timestamp; resize();
  camera.position.set(Math.sin(yaw) * 15, 15 * tilt, Math.cos(yaw) * 15); camera.lookAt(0, 0, 1);
  for (const mesh of avatars.values()) mesh.position.y = mesh.userData.y + (!reduced && ['Working','Thinking'].includes(mesh.userData.state) ? Math.sin(timestamp / 240) * .08 : 0);
  renderer.render(scene, camera);
}
document.getElementById('toggle-3d').addEventListener('click', () => {
  try {
    if (!renderer) { renderer = new THREE.WebGLRenderer({canvas, antialias:false, powerPreference:'low-power'}); renderer.setPixelRatio(1); }
    enabled = !enabled; canvas.hidden = !enabled;
    status.textContent = enabled ? 'Kéo để xoay · trạng thái từ Agent thật · tối đa 30 FPS' : 'Chế độ 2D đang hoạt động';
  } catch { enabled = false; canvas.hidden = true; status.textContent = 'WebGL không khả dụng. Dashboard 2D vẫn hoạt động.'; }
});
canvas.addEventListener('webglcontextlost', event => {event.preventDefault(); enabled = false; canvas.hidden = true; status.textContent = 'Mất WebGL, đã chuyển về 2D.';});
canvas.addEventListener('pointerdown', event => {dragging=true;previousX=event.clientX;canvas.setPointerCapture(event.pointerId);});
canvas.addEventListener('pointermove', event => {if(dragging){yaw+=(event.clientX-previousX)*.008;previousX=event.clientX;}});
canvas.addEventListener('pointerup', () => dragging=false);
window.addEventListener('agent-states', event => event.detail.forEach(agent => {
  const mesh = avatars.get(agent.id); if (mesh) {mesh.userData.state=agent.status;mesh.material.color.set(colors[agent.status] || colors.Offline);}
}));
requestAnimationFrame(render);
