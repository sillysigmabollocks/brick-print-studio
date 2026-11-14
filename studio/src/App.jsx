import { Component, lazy, Suspense, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowDownRight, ArrowUpRight, CircleHelp, Menu, Moon, RotateCcw, Sun, X } from 'lucide-react';
import { useGSAP } from '@gsap/react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Generator from './Generator.jsx';

gsap.registerPlugin(useGSAP, ScrollTrigger);
const StudioScene = lazy(() => import('./StudioScene.jsx'));
const repo = 'https://github.com/sillysigmabollocks/brick-print-studio';

const details = {
  about: {
    title: 'About the studio',
    description: 'Brick Print Studio matches LEGO set inventories to available LDraw models and lays out the required copies on 3MF plates for the Elegoo Centauri Carbon 2.',
    label: 'Open the workbench',
    href: '#generate',
  },
  projects: {
    title: 'X-wing assembly',
    description: 'A brick-built Star Wars X-wing comes together piece by piece in this interactive scene. Open the workbench to turn a real set inventory into print plates.',
    label: 'Generate a set',
    href: '#generate',
  },
  contact: {
    title: 'Connect',
    description: 'Have a bug report or an idea for Brick Print Studio? Open an issue in the project repository.',
    label: 'Open GitHub issues',
    href: repo + '/issues',
  },
};

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <rect width="48" height="48" rx="12" fill="currentColor" />
      <path d="M24 10.5 37 18v13L24 38.5 11 31V18L24 10.5Z" stroke="var(--logo-ink)" strokeWidth="1.65" strokeLinejoin="round" />
      <path d="m11.5 18.2 12.5 7 12.5-7M24 25.2v12.6" stroke="var(--logo-ink)" strokeWidth="1.65" />
      <path d="m18.5 16.5 5.5-3.1 5.5 3.1-5.5 3.1-5.5-3.1Z" fill="#E5C158" />
    </svg>
  );
}

function ThemeButton() {
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem('brick-print-theme') === 'dark'; }
    catch { return false; }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]').content = dark ? '#181819' : '#f5f5f7';
    try { localStorage.setItem('brick-print-theme', dark ? 'dark' : 'light'); } catch { /* Storage is optional. */ }
  }, [dark]);

  return (
    <button className="theme-button" type="button" aria-label="Dark mode" aria-pressed={dark} onClick={() => setDark(!dark)}>
      <Sun size={15} aria-hidden="true" className={!dark ? 'selected' : ''} />
      <Moon size={15} aria-hidden="true" className={dark ? 'selected' : ''} />
    </button>
  );
}

function SceneCard({ panel, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    if (panel && !dialog.current.open) {
      dialog.current.show();
      dialog.current.querySelector('button')?.focus({ preventScroll: true });
    }
    if (!panel && dialog.current.open) dialog.current.close();
  }, [panel]);

  const content = details[panel];
  return (
    <dialog ref={dialog} className="scene-card" aria-labelledby="scene-card-heading">
      {content && <>
        <button type="button" className="icon-button card-close" onClick={onClose} aria-label="Close details"><X size={18} /></button>
        <h3 id="scene-card-heading">{content.title}</h3>
        <p>{content.description}</p>
        <a className="text-link" href={content.href} onClick={() => onClose(false)}>{content.label} <ArrowUpRight size={15} aria-hidden="true" /></a>
      </>}
    </dialog>
  );
}

function ScenePreview({ unavailable = false }) {
  return (
    <div className="scene-preview">
      <img src="./showcase/studio-preview.webp" alt="Brick-built X-wing model on an isometric studio display stand" width="1000" height="665" />
      {unavailable && <span>Static preview</span>}
    </div>
  );
}

class SceneBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <ScenePreview unavailable /> : this.props.children;
  }
}

export default function App() {
  const [selection, setSelection] = useState(null);
  const panel = selection?.panel;
  const [menu, setMenu] = useState(false);
  const [replay, setReplay] = useState(0);
  const page = useRef(null);
  const visual = useRef(null);
  const menuButton = useRef(null);
  const trigger = useRef(null);

  function openPanel(name, event, view = name) {
    trigger.current = event?.currentTarget instanceof HTMLElement ? event.currentTarget : null;
    setSelection({ panel: name, view });
    setMenu(false);
    if (event?.currentTarget?.closest?.('header')) {
      visual.current.scrollIntoView({ block: 'nearest' });
    }
  }

  function closePanel(restoreFocus = true) {
    setSelection(null);
    if (restoreFocus) trigger.current?.focus({ preventScroll: true });
  }

  useEffect(() => {
    function onKey(event) {
      if (event.key !== 'Escape') return;
      if (panel) closePanel();
      else if (menu) {
        setMenu(false);
        menuButton.current.focus();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menu, panel]);

  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.from('.hero-copy > *', { y: 17, opacity: 0, duration: 0.64, stagger: 0.065, ease: 'power2.out', clearProps: 'transform,opacity' });
      gsap.fromTo('.generator-header', { y: 22 }, {
        y: 0,
        ease: 'none',
        scrollTrigger: { trigger: '.generator', start: 'top 100%', end: 'top 56%', scrub: 0.45 },
      });
    });
    return () => media.revert();
  }, { scope: page });

  return (
    <div className="site-shell" ref={page}>
      <header className="site-header flex items-center justify-between">
        <a className="brand flex items-center" href="./browser.html" aria-label="Brick Print Studio home">
          <Logo />
          <span>Brick Print<span className="brand-accent">.</span><br /><small>STUDIO</small></span>
        </a>
        <nav className="header-actions flex items-center" aria-label="Main navigation">
          <button className="connect" type="button" onClick={event => openPanel('contact', event)}>CONNECT <ArrowUpRight size={14} aria-hidden="true" /></button>
          <ThemeButton />
          <div className="menu-wrap">
            <button ref={menuButton} className="menu-button" type="button" aria-expanded={menu} aria-controls="site-menu" onClick={() => setMenu(!menu)}>MENU {menu ? <X size={16} aria-hidden="true" /> : <Menu size={16} aria-hidden="true" />}</button>
            <div id="site-menu" className="menu-popover" hidden={!menu}>
              <a href="#generate" onClick={() => setMenu(false)}>Workbench <ArrowDownRight size={15} aria-hidden="true" /></a>
              <button type="button" onClick={event => { openPanel('about', event); trigger.current = menuButton.current; }}>About <ArrowUpRight size={15} aria-hidden="true" /></button>
              <button type="button" onClick={event => { openPanel('projects', event); trigger.current = menuButton.current; }}>Projects <ArrowUpRight size={15} aria-hidden="true" /></button>
              <button type="button" onClick={event => { openPanel('contact', event); trigger.current = menuButton.current; }}>Contact <ArrowUpRight size={15} aria-hidden="true" /></button>
            </div>
          </div>
        </nav>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-heading">
          <div className="hero-copy">
            <p className="eyebrow"><span className="gold-dot" /> INDEPENDENT 3D PRINT STUDIO</p>
            <h1 id="hero-heading">From LEGO<br className="headline-break" /> set to<br className="headline-break" /> <span>print bed.</span></h1>
            <p className="hero-description">Turn a set number into ready-to-import 3MF plates, with the pieces and quantities already laid out.</p>
            <div className="hero-actions flex flex-wrap items-center">
              <a href="#generate" className="primary">Open the workbench <ArrowDownRight size={17} aria-hidden="true" /></a>
              <a className="jump-link" href="#studio" aria-label="Jump to the interactive studio"><ArrowDown size={18} aria-hidden="true" /></a>
            </div>
          </div>

          <figure className="visual" id="studio" ref={visual} aria-label="Interactive X-wing assembly studio">
            <div className="visual-grid" aria-hidden="true" />
            <div className="visual-title">
              <span><span className="scene-dot" /> INTERACTIVE STUDIO</span>
              <figcaption>X-wing assembly</figcaption>
            </div>
            <div className="scene">
              <SceneBoundary>
                <Suspense fallback={<ScenePreview />}>
                  <StudioScene view={selection?.view} replay={replay} onOpen={openPanel} fallback={<ScenePreview unavailable />} />
                </Suspense>
              </SceneBoundary>
            </div>
            <div className="scene-bottom flex items-end justify-between gap-3">
              <div className="scene-links flex flex-wrap gap-2" aria-label="Explore the studio">
                {Object.keys(details).map(name => <button key={name} type="button" aria-pressed={panel === name} onClick={event => openPanel(name, event)}>{name}</button>)}
              </div>
              <button className="replay icon-button" type="button" aria-label="Replay assembly" title="Replay assembly" onClick={() => { setSelection(null); setReplay(replay + 1); }}>
                <RotateCcw size={17} aria-hidden="true" />
              </button>
            </div>
            <SceneCard panel={panel} onClose={closePanel} />
          </figure>
        </section>
        <Generator />
      </main>
      <footer className="site-footer flex flex-wrap items-center justify-between gap-4">
        <span><CircleHelp size={15} aria-hidden="true" /> Catalog by <a href="https://rebrickable.com/downloads/">Rebrickable</a> · Models by <a href="https://library.ldraw.org/updates">LDraw</a></span>
        <a href={repo} className="text-link">Source on GitHub <ArrowUpRight size={15} aria-hidden="true" /></a>
      </footer>
    </div>
  );
}
