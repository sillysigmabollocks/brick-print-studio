import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrthographicCamera, useCursor } from '@react-three/drei';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { Color, Vector3 } from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const colors = {
  shell: '#d9d9d6', white: '#f3f1e9', shadow: '#85898a', joint: '#41474b',
  stripe: '#a33a30', glass: '#222b32', gold: '#e5c158',
};
const box = new RoundedBoxGeometry(1, 1, 1, 2, 0.09);
const views = {
  wide: { camera: [8, 6.2, 10.5], target: [0, 1.03, 0.15], zoom: 1 },
  about: { camera: [6.6, 5.1, 8.8], target: [-2.9, 1, -1.66], zoom: 1.58 },
  projects: { camera: [6.6, 4.6, 9.2], target: [0, 1.72, 0.15], zoom: 1.32 },
  chair: { camera: [5.9, 4.7, 9.2], target: [-2.85, 0.67, 0.95], zoom: 1.58 },
  contact: { camera: [8.4, 5.3, 8.7], target: [3.05, 1.13, -1.75], zoom: 1.65 },
};

function Block({ at = [0, 0, 0], size, color, rotation, metalness = 0.05, roughness = 0.53 }) {
  return (
    <mesh geometry={box} position={at} scale={size} rotation={rotation}>
      <meshStandardMaterial color={color} metalness={metalness} roughness={roughness} />
    </mesh>
  );
}

function Studs({ columns, rows, width, depth, y, color }) {
  return Array.from({ length: columns * rows }, (_, i) => (
    <mesh key={i} position={[
      ((i % columns + 0.5) / columns - 0.5) * width,
      y,
      ((Math.floor(i / columns) + 0.5) / rows - 0.5) * depth,
    ]}>
      <cylinderGeometry args={[0.064, 0.067, 0.039, 10]} />
      <meshStandardMaterial color={color} roughness={0.44} />
    </mesh>
  ));
}

function Brick({ size, color, studs }) {
  return <>
    <Block size={size} color={color} />
    {studs && <Studs columns={studs[0]} rows={studs[1]} width={size[0]} depth={size[2]} y={size[1] / 2 + 0.018} color={color} />}
  </>;
}

function makeShip() {
  const pieces = [];
  const add = (at, size, color, studs, rotation) => pieces.push({ at, size, color, studs, rotation });
  const { shell, white, shadow, joint, stripe, glass } = colors;

  add([0, 0, 0], [0.78, 0.34, 2.94], shadow, [3, 12]);
  add([0, 0.23, -0.56], [0.87, 0.23, 1.7], shell, [4, 7]);
  add([0, 0.21, 1.2], [0.56, 0.21, 1.72], white, [2, 7]);
  add([0, 0.13, 2.13], [0.41, 0.23, 0.44], white, [2, 2]);
  add([0, 0.16, 2.39], [0.3, 0.16, 0.21], shadow);
  add([0, 0.42, -0.06], [0.56, 0.26, 0.71], glass, null, [0.12, 0, 0]);
  add([0, 0.36, 0.39], [0.53, 0.14, 0.24], glass, null, [0.28, 0, 0]);
  add([0, 0.41, -0.63], [0.66, 0.21, 0.28], white, [3, 1]);
  add([0, 0.52, -0.89], [0.22, 0.18, 0.24], white, [1, 1]);
  add([0, 0.17, -1.63], [0.49, 0.26, 0.34], joint, [2, 1]);

  for (const side of [-1, 1]) {
    add([side * 0.34, 0.21, 0.99], [0.16, 0.12, 1.3], stripe);
    add([side * 0.24, 0.19, 1.95], [0.13, 0.11, 0.56], shell);
    add([side * 0.45, 0.18, -0.55], [0.15, 0.33, 1.26], white, [1, 5]);
    for (const level of [-1, 1]) {
      const slope = side * level * 0.29;
      const point = (x, z, lift = 0) => [side * x, level * (0.05 + x * 0.29) + lift, z];
      const wing = (x, z, size, color, studs, lift) => add(point(x, z, lift), size, color, studs, [0, 0, slope]);

      wing(1.01, -0.51, [1.05, 0.15, 1.36], shell, [5, 6]);
      wing(1.54, -0.65, [0.78, 0.14, 1.08], white, [3, 5]);
      wing(1.99, -0.84, [0.46, 0.15, 0.74], shell, [2, 3]);
      wing(1.67, -0.7, [0.25, 0.06, 1.01], stripe, [1, 4], 0.10);
      wing(1.25, -1.12, [0.62, 0.11, 0.15], shadow, [3, 1]);
      wing(2.25, -0.83, [0.23, 0.24, 0.53], shadow, [1, 2]);
      wing(2.28, -0.48, [0.19, 0.17, 0.64], joint);
      wing(2.28, 0.02, [0.09, 0.09, 0.61], shell);
      wing(2.28, 0.36, [0.13, 0.12, 0.1], white);
      wing(0.73, -0.88, [0.47, 0.44, 0.95], shadow);
      wing(0.73, -0.29, [0.41, 0.37, 0.22], white);
      wing(0.73, -0.16, [0.24, 0.24, 0.06], joint);
      wing(0.73, -1.44, [0.38, 0.36, 0.29], joint);
      wing(0.73, -1.63, [0.27, 0.27, 0.12], stripe);
    }
  }
  return pieces;
}

const shipPieces = makeShip();

function Ship({ replay, onOpen, reduced }) {
  const items = useRef([]);
  const [hovered, setHovered] = useState(false);
  useCursor(hovered, 'pointer', 'auto');
  useGSAP(() => {
    const assembly = gsap.timeline({ delay: replay ? 0.07 : 0.28 });
    items.current.forEach((item, i) => {
      const { at } = shipPieces[i];
      const angle = i * 2.39996;
      const distance = 0.65 + (i % 7) * 0.13;
      if (reduced) return;
      const start = i * 0.039;
      assembly.fromTo(item.position, {
        x: at[0] + Math.cos(angle) * distance,
        y: at[1] + 0.6 + (i % 5) * 0.20,
        z: at[2] + Math.sin(angle) * distance,
      }, { x: at[0], y: at[1], z: at[2], duration: 1.27, ease: 'power2.inOut' }, start);
      assembly.fromTo(item.scale, { x: 0.45, y: 0.45, z: 0.45 }, { x: 1, y: 1, z: 1, duration: 0.77 }, start);
    });
  }, { dependencies: [replay, reduced], revertOnUpdate: true });

  return (
    <group
      position={[0.12, 1.82, 0.34]}
      rotation={[0, -0.21, 0]}
      onPointerOver={event => { event.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
      onClick={event => { event.stopPropagation(); onOpen('projects'); }}
    >
      {shipPieces.map(({ at, size, color, studs, rotation }, i) => (
        <group key={i} position={at} rotation={rotation} ref={item => { items.current[i] = item; }}>
          <Brick size={size} color={color} studs={studs} />
        </group>
      ))}
    </group>
  );
}

function Hotspot({ name, view = name, at, labelHeight, onOpen, children }) {
  const [hovered, setHovered] = useState(false);
  useCursor(hovered, 'pointer', 'auto');
  return (
    <group
      position={at}
      onPointerOver={event => { event.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
      onClick={event => { event.stopPropagation(); onOpen(name, undefined, view); }}
    >
      {children}
      <mesh position={[0, labelHeight, 0.12]}>
        <sphereGeometry args={[0.09, 18, 12]} />
        <meshStandardMaterial color={hovered ? '#fff1a1' : colors.gold} emissive={colors.gold} emissiveIntensity={hovered ? 1.25 : 0.45} />
      </mesh>
    </group>
  );
}

function Room({ onOpen }) {
  const floor = '#565553';
  const side = '#323331';
  const shelf = '#77736a';
  return <>
    <Block at={[0, -0.23, 0]} size={[8.25, 0.40, 5.75]} color={side} />
    <Block at={[0, -0.025, 0]} size={[8.18, 0.13, 5.68]} color={floor} />
    <gridHelper position={[0, 0.045, 0]} scale={[8.05, 1, 5.53]} args={[1, 18, '#605f5b', '#65635d']} />
    <Block at={[0, 0.055, 0.42]} size={[3.65, 0.025, 3.45]} color="#3d3e3c" />
    <Block at={[0.17, 0.20, 0.31]} size={[1.44, 0.35, 1.35]} color="#3d403e" />
    <Block at={[0.17, 0.39, 0.31]} size={[1.36, 0.095, 1.28]} color="#777670" />
    <Block at={[0.17, 0.94, 0.31]} size={[0.16, 1.06, 0.28]} color="#5e615e" />
    <Block at={[0.17, 1.45, 0.31]} size={[0.64, 0.09, 0.55]} color="#777670" />
    <Hotspot name="about" at={[-2.85, 0, -1.54]} labelHeight={1.67} onOpen={onOpen}>
      <Block at={[0, 0.8, 0]} size={[1.55, 0.16, 0.92]} color={shelf} />
      {[-0.61, 0.61].map(x => <Block key={x} at={[x, 0.39, 0]} size={[0.1, 0.74, 0.68]} color={side} />)}
      <Block at={[-0.23, 1.17, -0.15]} size={[0.62, 0.47, 0.11]} color="#262a2c" />
      <Block at={[-0.23, 1.19, -0.086]} size={[0.54, 0.36, 0.025]} color="#9d9d91" />
      <Block at={[-0.22, 0.94, -0.14]} size={[0.21, 0.13, 0.15]} color={side} />
      <Block at={[-0.19, 0.91, 0.17]} size={[0.43, 0.05, 0.18]} color="#b7b3a2" />
      <Block at={[0.48, 1.15, -0.22]} size={[0.07, 0.57, 0.08]} color={side} />
      <Block at={[0.40, 1.43, -0.22]} size={[0.26, 0.09, 0.16]} color={colors.gold} />
    </Hotspot>
    <Hotspot name="projects" view="chair" at={[-2.85, 0, 0.95]} labelHeight={1.21} onOpen={onOpen}>
      <Block at={[0, 0.47, 0]} size={[0.67, 0.12, 0.65]} color="#aa8a51" />
      <Block at={[0, 0.77, 0.27]} size={[0.67, 0.55, 0.12]} color="#aa8a51" />
      <Block at={[0, 0.24, 0]} size={[0.08, 0.36, 0.09]} color={side} />
      <Block at={[0, 0.08, 0]} size={[0.63, 0.08, 0.53]} color={side} />
    </Hotspot>
    <Hotspot name="contact" at={[2.98, 0, -1.59]} labelHeight={2.01} onOpen={onOpen}>
      {[-0.57, 0.57].map(x => <Block key={x} at={[x, 0.9, 0]} size={[0.09, 1.7, 0.55]} color={side} />)}
      {[0.18, 0.71, 1.22, 1.74].map(y => <Block key={y} at={[0, y, 0]} size={[1.16, 0.08, 0.55]} color={shelf} />)}
      {['#d2c9ae', '#a58048', '#787e78', '#b0a594'].map((color, i) =>
        <Block key={i} at={[-0.38 + 0.17 * i, 1.45, 0.05]} size={[0.13, 0.36 - (i % 2) * 0.08, 0.34]} color={color} rotation={[0, 0, i === 3 ? -0.19 : 0]} />
      )}
      <Block at={[0.19, 0.94, 0.03]} size={[0.5, 0.32, 0.4]} color="#958b73" />
      <Block at={[-0.24, 0.34, 0.05]} size={[0.46, 0.22, 0.38]} color="#555b57" />
    </Hotspot>
  </>;
}

function Camera({ view, reduced }) {
  const pose = useMemo(() => ({ x: 8, y: 6.2, z: 10.5, tx: 0, ty: 1.03, tz: 0.15, zoom: 1 }), []);
  const lookAt = useMemo(() => new Vector3(), []);
  const { size, gl } = useThree();
  useEffect(() => {
    const { camera: [x, y, z], target: [tx, ty, tz], zoom } = views[view] ?? views.wide;
    const transition = gsap.to(pose, { x, y, z, tx, ty, tz, zoom, duration: reduced ? 0 : 1.08, ease: 'power3.inOut' });
    return () => transition.kill();
  }, [pose, view, reduced]);

  useFrame(({ camera, pointer }) => {
    const parallax = !view && !reduced && gl.domElement.matches(':hover') ? 1 : 0;
    const x = pose.x + pointer.x * 0.48 * parallax;
    const y = pose.y + pointer.y * 0.32 * parallax;
    if (reduced) camera.position.set(x, y, pose.z);
    else {
      camera.position.x += (x - camera.position.x) * 0.13;
      camera.position.y += (y - camera.position.y) * 0.13;
      camera.position.z += (pose.z - camera.position.z) * 0.13;
    }
    camera.lookAt(lookAt.set(pose.tx, pose.ty, pose.tz));
    camera.zoom = Math.min(size.width / 9.8, size.height / 6.5) * pose.zoom;
    camera.updateProjectionMatrix();
  });
  return <OrthographicCamera makeDefault position={views.wide.camera} near={0.1} far={60} />;
}

export default function StudioScene({ view, replay, onOpen, fallback }) {
  const container = useRef(null);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    if (!container.current) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const [available] = useState(() => {
    try {
      const context = document.createElement('canvas').getContext('webgl2');
      context?.getExtension('WEBGL_lose_context')?.loseContext();
      return Boolean(context);
    } catch {
      return false;
    }
  });
  const [reduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  if (!available) return fallback;
  return (
    <div className="canvas-wrap" ref={container}>
      <Canvas dpr={[1, 1.65]} frameloop={visible ? 'always' : 'never'} gl={{ alpha: true, antialias: true }} fallback={fallback}>
        <ambientLight intensity={1.12} />
        <hemisphereLight args={[new Color('#f6f1e3'), new Color('#696d74'), 1.62]} />
        <directionalLight position={[2, 8, 5]} intensity={3} color="#fff4db" />
        <directionalLight position={[-6, 4, -3]} intensity={1.05} color="#c7d6ec" />
        <Camera view={view} reduced={reduced} />
        <Room onOpen={onOpen} />
        <Ship replay={replay} onOpen={onOpen} reduced={reduced} />
      </Canvas>
    </div>
  );
}
