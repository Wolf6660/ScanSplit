'use strict';
const $ = (id) => document.getElementById(id);
const names = {whole:'Ganze Seite',split:'Beide Hälften',left:'Nur links',right:'Nur rechts',skip:'Auslassen'};
const state = {doc:null,current:0,selected:new Set(),choices:[],ocr:true,busy:false,uploading:false,job:null,timer:null,health:null};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('Der Server hat keine gültige Antwort geliefert.'); }
  if (!response.ok) {
    const error = new Error(data.error || 'Die Anfrage ist fehlgeschlagen.'); error.status = response.status; throw error;
  }
  return data;
}
function message(text = '') { $('message').textContent = text; $('message').hidden = !text; }
function total() { return state.choices.reduce((n,c) => n + (c.mode === 'split' ? 2 : c.mode === 'skip' ? 0 : 1),0); }
function previewURL(index, thumb = false) {
  return `/api/documents/${state.doc.id}/preview/${index}?rotation=${state.choices[index].rotation}${thumb ? '&kind=thumb' : ''}`;
}
function updateSummary() {
  const count = total(); $('output-count').textContent = `${count} A4-Seiten`;
  $('export-button').disabled = state.busy || !count;
  $('selection-count').textContent = `${state.selected.size} Scan${state.selected.size === 1 ? '' : 's'} ausgewählt`;
  $('apply-selection').disabled = state.busy || state.selected.size < 2;
}
function saveDraft() {
  if (!state.doc) return;
  try { sessionStorage.setItem('scansplit',JSON.stringify({id:state.doc.id,choices:state.choices,ocr:state.ocr,job:state.job?.id || null})); } catch { /* Storage is optional. */ }
}
function renderPages() {
  const list = $('page-list'); list.replaceChildren();
  state.doc.pages.forEach((_,i) => {
    const card = document.createElement('div'); card.className = 'page-card'; card.id = `card-${i}`;
    const check = document.createElement('input'); check.type = 'checkbox'; check.className = 'page-select';
    check.setAttribute('aria-label',`Scan ${i+1} zur Mehrfachauswahl hinzufügen`);
    check.addEventListener('change',() => {
      if (check.checked) state.selected.add(i); else state.selected.delete(i);
      if (!state.selected.size) state.selected.add(state.current);
      updateCards(); updateSummary();
    });
    const button = document.createElement('button'); button.type = 'button'; button.setAttribute('aria-label',`Scan ${i+1} bearbeiten`);
    const image = document.createElement('img'); image.loading = 'lazy'; image.alt = ''; image.src = previewURL(i,true);
    const title = document.createElement('strong'); title.textContent = `Scan ${i+1}`;
    const subtitle = document.createElement('small'); subtitle.textContent = names[state.choices[i].mode];
    button.append(image,title,subtitle);
    button.addEventListener('click',(event) => selectPage(i,event));
    card.append(check,button); list.append(card);
  });
  updateCards();
}
function updateCards() {
  state.choices.forEach((choice,i) => {
    const card = $(`card-${i}`); if (!card) return;
    card.classList.toggle('current',state.current === i); card.classList.toggle('selected',state.selected.has(i));
    card.querySelector('input').checked = state.selected.has(i);
    card.querySelector('input').disabled = state.busy;
    card.querySelector('button').disabled = state.busy;
    card.querySelector('button').setAttribute('aria-current',state.current === i ? 'page' : 'false');
    card.querySelector('small').textContent = names[choice.mode];
  });
}
function selectPage(index, event = {}) {
  if (state.busy || index < 0 || index >= state.choices.length) return;
  if (event.shiftKey) {
    const from = Math.min(state.current,index), to = Math.max(state.current,index);
    for (let i = from; i <= to; i++) state.selected.add(i);
  } else if (event.ctrlKey || event.metaKey) {
    if (state.selected.has(index)) state.selected.delete(index); else state.selected.add(index);
  } else state.selected = new Set([index]);
  state.current = index;
  if (!state.selected.size) state.selected.add(index);
  updateCards(); showPreview(); updateSummary();
}
function fitPreview() {
  if (!state.doc) return;
  const page = state.doc.pages[state.current], choice = state.choices[state.current];
  const rotated = choice.rotation % 180 !== 0;
  const ratio = rotated ? page.height/page.width : page.width/page.height;
  const area = $('preview-area');
  const width = Math.max(100,Math.min(area.clientWidth - 44,(area.clientHeight - 44)*ratio));
  $('sheet').style.width = `${width}px`; $('sheet').style.height = `${width/ratio}px`;
}
function updateOverlay() {
  if (!state.doc) return;
  const c = state.choices[state.current], cut = c.cut*100;
  const split = ['split','left','right'].includes(c.mode);
  $('divider').hidden = !split; $('divider').style.left = `${cut}%`;
  $('divider').setAttribute('aria-valuenow',cut.toFixed(1));
  $('divider').setAttribute('aria-valuetext',`${cut.toFixed(1)} Prozent`);
  $('shade-left').hidden = c.mode !== 'right'; $('shade-left').style.width = `${cut}%`;
  $('shade-right').hidden = c.mode !== 'left'; $('shade-right').style.width = `${100-cut}%`;
  $('shade-all').hidden = c.mode !== 'skip';
  $('cut-range').value = cut; $('cut-value').textContent = `${Number(cut.toFixed(1))} %`;
  $('cut-range').disabled = state.busy || !split; $('center-line').disabled = state.busy || !split;
  $('preview-caption').textContent = split ? 'Die orange Linie lässt sich direkt verschieben.' : c.mode === 'skip' ? 'Dieser Scan wird nicht in die Ausgabe übernommen.' : 'Die ganze Seite wird proportional auf A4 eingepasst.';
}
function showPreview() {
  const i = state.current;
  $('page-mode').value = state.choices[i].mode; $('active-scan').textContent = `Scan ${i+1}`;
  $('preview-title').textContent = `Scan ${i+1} · Vorschau`; $('page-position').textContent = `${i+1} / ${state.choices.length}`;
  $('previous-page').disabled = state.busy || i === 0; $('next-page').disabled = state.busy || i === state.choices.length-1;
  $('preview-loading').hidden = false;
  $('preview-image').src = previewURL(i); $('preview-image').alt = `Vorschau von Scan ${i+1}`;
  fitPreview(); updateOverlay();
}
function editChoice(fields) {
  if (state.busy || !state.doc) return;
  Object.assign(state.choices[state.current],fields); state.job = null; $('job-panel').hidden = true;
  updateOverlay(); updateCards(); updateSummary(); saveDraft();
}
function renderOCR() {
  $('ocr-toggle').checked = state.ocr; $('ocr-card').classList.toggle('active',state.ocr);
  $('ocr-state').textContent = state.ocr ? 'Aktiviert' : 'Deaktiviert';
  const unavailable = state.ocr && state.health && !state.health.ocr_available;
  $('ocr-availability').hidden = !unavailable; $('ocr-availability').textContent = unavailable ? state.health.ocr_message : '';
}
function setBusy(busy) {
  state.busy = busy;
  for (const id of ['replace-file','delete-document','page-mode','rotate-page','ocr-toggle']) $(id).disabled = busy;
  updateCards(); updateOverlay(); updateSummary();
  $('previous-page').disabled = busy || state.current === 0;
  $('next-page').disabled = busy || state.current === state.choices.length-1;
}
function useDocument(doc, draft = null) {
  state.doc = doc; state.current = 0; state.selected = new Set([0]); state.job = null;
  const validDraft = draft && Array.isArray(draft.choices) && draft.choices.length === doc.pages.length && draft.choices.every(c =>
    c && Object.hasOwn(names,c.mode) && typeof c.cut === 'number' && c.cut >= .1 && c.cut <= .9 && [0,90,180,270].includes(c.rotation));
  state.choices = validDraft ? draft.choices : doc.pages.map(({mode,cut,rotation}) => ({mode,cut,rotation}));
  state.ocr = draft && typeof draft.ocr === 'boolean' ? draft.ocr : true;
  $('upload-panel').hidden = true; $('workspace').hidden = false; $('replace-file').hidden = false; $('job-panel').hidden = true;
  $('document-name').textContent = doc.name; $('document-detail').textContent = `${doc.pages.length} Scan-Seiten · Querformat wird zum Teilen vorgeschlagen`;
  $('scan-count').textContent = doc.pages.length;
  $('retention-note').textContent = `Dateien verfügbar bis ${new Date(doc.expires_at*1000).toLocaleString('de-DE')}.`;
  renderPages(); renderOCR(); setBusy(false); showPreview(); saveDraft();
}
async function upload(file) {
  if (!file || state.busy || state.uploading) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) { message('Bitte eine PDF-Datei auswählen.'); return; }
  const maxMB = state.health?.max_upload_mb || 250;
  if (file.size > maxMB*1024*1024) { message(`Die PDF darf höchstens ${maxMB} MB groß sein.`); return; }
  state.uploading = true; $('choose-file').disabled = true; $('replace-file').disabled = true;
  $('upload-status').textContent = 'PDF wird hochgeladen und geprüft …'; message();
  try {
    const doc = await api('/api/documents',{method:'POST',headers:{'Content-Type':'application/pdf','X-File-Name':encodeURIComponent(file.name)},body:file});
    if (state.timer) clearTimeout(state.timer);
    useDocument(doc);
  } catch (error) { message(error.message); }
  finally { state.uploading = false; $('choose-file').disabled = false; $('replace-file').disabled = false; $('upload-status').textContent = ''; $('file-input').value = ''; }
}
async function startExport() {
  if (state.busy || !state.doc) return;
  message(); setBusy(true); $('job-panel').hidden = false; $('download-result').hidden = true;
  $('job-title').textContent = 'Export wird vorbereitet'; $('job-message').textContent = 'Einstellungen werden übermittelt …';
  $('job-progress').value = 0; $('job-progress').max = total(); $('cancel-job').hidden = true;
  try {
    const job = await api(`/api/documents/${state.doc.id}/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choices:state.choices,ocr:state.ocr})});
    state.job = job; saveDraft(); applyJob(job); pollJob(state.doc.id,job.id);
    $('job-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
  } catch(error) { setBusy(false); $('job-title').textContent = 'Export konnte nicht starten'; $('job-message').textContent = error.message; $('job-hint').textContent = 'Bei OCR-Problemen den roten Schalter ausschalten und erneut versuchen.'; message(error.message); }
}
function applyJob(job) {
  state.job = job;
  const running = ['queued','running','cancelling'].includes(job.state);
  setBusy(running); $('job-panel').hidden = false;
  $('job-title').textContent = {queued:'Dein Export wartet',running:job.ocr ? 'Seiten teilen & Text erkennen' : 'Seiten werden geteilt',completed:'Deine A4-PDF ist fertig',cancelled:'Export abgebrochen',failed:'Export fehlgeschlagen'}[job.state] || 'Export';
  $('job-message').textContent = job.message; $('job-progress').max = job.total; $('job-progress').value = job.done;
  $('cancel-job').hidden = !running; $('cancel-job').disabled = false;
  $('download-result').hidden = job.state !== 'completed';
  if (job.state === 'completed') { $('download-result').href = `/api/documents/${state.doc.id}/jobs/${job.id}/result.pdf`; $('download-result').setAttribute('download',''); }
  $('job-hint').textContent = running ? 'Du kannst den Export abbrechen. Auf kleinen Geräten benötigt OCR etwas Geduld.' : job.state === 'failed' ? 'Falls OCR die Ursache ist: ausschalten und dieselbe PDF erneut verarbeiten.' : job.state === 'completed' ? `${job.total} A4-Seiten · ${job.ocr ? 'mit deutscher Texterkennung' : 'ohne OCR'} · Original unverändert` : 'Die Einstellungen können jetzt wieder angepasst werden.';
  saveDraft();
}
async function pollJob(docID, jobID) {
  if (state.doc?.id !== docID || state.job?.id !== jobID) return;
  try {
    const job = await api(`/api/documents/${docID}/jobs/${jobID}`); applyJob(job);
    if (['queued','running','cancelling'].includes(job.state)) state.timer = setTimeout(() => pollJob(docID,jobID),1000);
  } catch(error) {
    if (error.status === 404) { setBusy(false); message(error.message); return; }
    $('job-message').textContent = 'Verbindung unterbrochen. Status wird erneut abgefragt …';
    state.timer = setTimeout(() => pollJob(docID,jobID),3000);
  }
}

$('choose-file').addEventListener('click',() => $('file-input').click());
$('replace-file').addEventListener('click',() => $('file-input').click());
$('file-input').addEventListener('change',event => upload(event.target.files[0]));
for (const name of ['dragenter','dragover']) $('upload-panel').addEventListener(name,event => { event.preventDefault(); $('upload-panel').classList.add('dragover'); });
for (const name of ['dragleave','drop']) $('upload-panel').addEventListener(name,event => { event.preventDefault(); $('upload-panel').classList.remove('dragover'); });
$('upload-panel').addEventListener('drop',event => upload(event.dataTransfer.files[0]));
$('page-mode').addEventListener('change',event => editChoice({mode:event.target.value}));
$('cut-range').addEventListener('input',event => editChoice({cut:Number(event.target.value)/100}));
$('center-line').addEventListener('click',() => editChoice({cut:.5}));
$('rotate-page').addEventListener('click',() => {
  editChoice({rotation:(state.choices[state.current].rotation+90)%360});
  $(`card-${state.current}`).querySelector('img').src = previewURL(state.current,true); showPreview();
});
$('apply-selection').addEventListener('click',() => {
  if (state.busy) return;
  const choice = {...state.choices[state.current]};
  for (const i of state.selected) state.choices[i] = {...choice};
  state.job = null; $('job-panel').hidden = true; renderPages(); showPreview(); updateSummary(); saveDraft();
});
$('ocr-toggle').addEventListener('change',event => { state.ocr = event.target.checked; renderOCR(); saveDraft(); });
$('export-button').addEventListener('click',startExport);
$('previous-page').addEventListener('click',() => selectPage(state.current-1));
$('next-page').addEventListener('click',() => selectPage(state.current+1));
$('preview-image').addEventListener('load',() => { $('preview-loading').hidden = true; fitPreview(); });
$('preview-image').addEventListener('error',() => { $('preview-loading').textContent = 'Vorschau konnte nicht geladen werden. Bitte Seite erneut auswählen.'; });
new ResizeObserver(fitPreview).observe($('preview-area'));
$('divider').addEventListener('pointerdown',event => {
  if (state.busy || !state.doc) return;
  event.preventDefault(); $('divider').setPointerCapture(event.pointerId);
});
$('divider').addEventListener('pointermove',event => {
  if (!$('divider').hasPointerCapture(event.pointerId) || state.busy) return;
  const box = $('sheet').getBoundingClientRect(); editChoice({cut:Math.max(.1,Math.min(.9,(event.clientX-box.left)/box.width))});
});
$('divider').addEventListener('pointerup',event => { if ($('divider').hasPointerCapture(event.pointerId)) $('divider').releasePointerCapture(event.pointerId); });
$('divider').addEventListener('keydown',event => {
  if (!['ArrowLeft','ArrowRight','Home'].includes(event.key) || state.busy || !state.doc) return;
  event.preventDefault(); const delta = event.key === 'ArrowLeft' ? -.005 : .005;
  editChoice({cut:event.key === 'Home' ? .5 : Math.max(.1,Math.min(.9,state.choices[state.current].cut+delta))});
});
$('cancel-job').addEventListener('click',async () => {
  if (!state.job) return; $('cancel-job').disabled = true;
  try { await api(`/api/documents/${state.doc.id}/jobs/${state.job.id}/cancel`,{method:'POST'}); $('job-message').textContent = 'Export wird abgebrochen …'; }
  catch(error) { message(error.message); $('cancel-job').disabled = false; }
});
$('delete-document').addEventListener('click',async () => {
  if (state.busy || !state.doc) return;
  try {
    await api(`/api/documents/${state.doc.id}`,{method:'DELETE'});
    if (state.timer) clearTimeout(state.timer);
    state.doc = null; state.job = null; state.choices = []; sessionStorage.removeItem('scansplit');
    $('workspace').hidden = true; $('upload-panel').hidden = false; $('replace-file').hidden = true; message();
  } catch(error) { message(error.message); }
});
async function init() {
  try {
    state.health = await api('/api/health'); $('version').textContent = `v${state.health.version}`;
    $('upload-hint').textContent = `PDF · bis zu ${state.health.max_upload_mb} MB · keine Cloud-Übertragung`; renderOCR();
    if (!state.health.renderer_available) message('Die PDF-Vorschau ist auf diesem Server nicht verfügbar. Poppler muss installiert sein.');
  } catch(error) { message('Server nicht erreichbar. Bitte die Seite erneut laden.'); }
  try {
    const draft = JSON.parse(sessionStorage.getItem('scansplit') || 'null');
    if (draft?.id) {
      const doc = await api(`/api/documents/${draft.id}`); useDocument(doc,draft);
      if (draft.job) { const job = await api(`/api/documents/${doc.id}/jobs/${draft.job}`); applyJob(job); if (['queued','running','cancelling'].includes(job.state)) pollJob(doc.id,job.id); }
    }
  } catch { try { sessionStorage.removeItem('scansplit'); } catch { /* Optional. */ } }
}
init();
