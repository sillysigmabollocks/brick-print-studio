import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowRight, Box, ChevronDown, SlidersHorizontal } from 'lucide-react';
import { setNumber } from './set-number.js';

function Toggle({ name, children, defaultChecked, onChange }) {
  return (
    <label className="option-row">
      <span>{children}</span>
      <input className="switch" type="checkbox" name={name} defaultChecked={defaultChecked} onChange={onChange} />
    </label>
  );
}

const idleStatus = 'Your download will appear here after the plates are built.';

export default function Generator() {
  const [groupByColor, setGroupByColor] = useState(true);
  const [skipStand, setSkipStand] = useState(true);
  const [status, setStatus] = useState(idleStatus);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [download, setDownload] = useState(null);
  const worker = useRef(null);
  const objectUrl = useRef(null);

  useEffect(() => () => {
    worker.current?.terminate();
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  function fail(message) {
    worker.current?.terminate();
    worker.current = null;
    setBusy(false);
    setStatus('Could not generate the print ZIP.');
    setError(message);
  }

  function startWorker() {
    const instance = new Worker(new URL('./worker.js?v=display-stand-1', window.location.href), { type: 'module' });
    instance.onmessage = ({ data }) => {
      if (data.type === 'progress') {
        setStatus(data.message);
      } else if (data.type === 'error') {
        fail(data.message);
      } else if (data.type === 'complete') {
        const summary = data.result;
        const counts = `${summary.plates} plates · ${summary.checked + summary.review} of ${summary.required} copies placed · ${summary.missing} unplaced.`;
        const figures = summary.missing_figure_inventories;
        const stand = {
          skipped: `Skipped ${summary.display_stand_copies_skipped} display stand pieces.`,
          unmapped: 'No verified stand list for this set. Use the manual stand list to skip pieces.',
          inventory_mismatch: 'The verified stand list differs from this inventory. Use the manual stand list to skip pieces.',
        }[summary.display_stand_status];
        setStatus([counts, stand, figures && `Missing catalog inventories for ${figures} minifigure(s).`].filter(Boolean).join(' '));
        objectUrl.current = URL.createObjectURL(new Blob([data.bytes], { type: 'application/zip' }));
        setDownload({ href: objectUrl.current, filename: summary.filename });
        setBusy(false);
      }
    };
    instance.onerror = () => fail('The browser print engine could not start. Reload the page and try again.');
    return instance;
  }

  function generate(event) {
    event.preventDefault();
    if (busy) return;
    setError('');
    const form = new FormData(event.currentTarget);
    try {
      const set = setNumber(form.get('set'));
      worker.current ??= startWorker();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
      setDownload(null);
      setBusy(true);
      setStatus(`Preparing set ${set}…`);
      worker.current.postMessage({
        set,
        limit: groupByColor ? Number(form.get('limit')) : 30,
        calibration: form.has('calibration'),
        groupByColor,
        includeMinifigures: form.has('includeMinifigures'),
        includeProjectiles: form.has('includeProjectiles'),
        skipDisplayStand: skipStand,
        manualStand: form.get('manualStand') ?? '',
      });
    } catch (problem) {
      setBusy(false);
      setError(problem.message);
    }
  }

  return (
    <section className="generator" id="generate" aria-labelledby="generator-heading">
      <div className="generator-header flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow"><span className="gold-dot" /> PRINT WORKBENCH</p>
          <h2 id="generator-heading">Generate a set<span>.</span></h2>
        </div>
        <div className="printer-chip"><Box size={15} aria-hidden="true" /> Elegoo Centauri Carbon 2</div>
      </div>
      <div className="workbench-grid">
        <form onSubmit={generate} autoComplete="off" className="workbench-card">
          <label htmlFor="set" className="field-label">Set number or link</label>
          <div className="set-field">
            <input id="set" name="set" placeholder="75394 or a LEGO set link" maxLength={500} spellCheck={false} required aria-describedby="set-help" />
            <button className="primary" type="submit" disabled={busy}>
              {busy ? 'Generating…' : 'Generate Print ZIP'} <ArrowRight size={17} aria-hidden="true" />
            </button>
          </div>
          <p className="hint" id="set-help">Supports LEGO, BrickLink, Rebrickable, and Brickset links.</p>
          <details open className="print-options">
            <summary><SlidersHorizontal size={16} aria-hidden="true" /> Printing options <ChevronDown className="chevron" size={16} aria-hidden="true" /></summary>
            <Toggle name="groupByColor" defaultChecked onChange={event => setGroupByColor(event.target.checked)}>Group plates by LEGO color</Toggle>
            <p className="hint option-hint">Turn off to mix colors and fill the available bed space.</p>
            <Toggle name="includeMinifigures">Include minifigures</Toggle>
            <Toggle name="includeProjectiles">Include projectiles</Toggle>
            <Toggle name="skipStand" defaultChecked onChange={event => setSkipStand(event.target.checked)}>Skip display stand</Toggle>
            <details className="manual-stand" hidden={!skipStand}>
              <summary>Manual stand list</summary>
              <label className="hint" htmlFor="manual-stand">For an unlisted stand or to override the verified list, enter part number, Rebrickable color ID, and quantity on each line. Black is color 0.</label>
              <textarea id="manual-stand" name="manualStand" rows={3} maxLength={12000} placeholder="3023,0,2" spellCheck={false} disabled={!skipStand} />
            </details>
            <label className="option-row">
              <span>Maximum copies per plate</span>
              <input name="limit" type="number" min="1" max="100" defaultValue="30" disabled={!groupByColor} required />
            </label>
            <Toggle name="calibration">Include a stud-and-tube fit test</Toggle>
          </details>
          <p className="hint first-run">The first run downloads about 160 MB of catalog and model data, plus the browser engine. Keep this tab open during generation.</p>
        </form>
        <section className="workbench-card output-card" aria-labelledby="output-heading">
          <div className="output-icon"><ArrowDownToLine size={20} aria-hidden="true" /></div>
          <h3 id="output-heading">Print ZIP</h3>
          <p role="status" aria-live="polite" className="output-status">{status}</p>
          {error && <p className="error" role="alert">{error}</p>}
          {download && <a className="primary" href={download.href} download={download.filename}><ArrowDownToLine size={16} aria-hidden="true" /> Download Print ZIP</a>}
          <p className="hint output-note">Open the 3MF files in <code>Printing_Batches</code> in your slicer. Check the included reports for missing models and meshes that need review.</p>
          <a className="text-link" href="./">GitHub Actions generator <ArrowRight size={14} aria-hidden="true" /></a>
        </section>
      </div>
    </section>
  );
}
