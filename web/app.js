'use strict';
const $ = (id) => document.getElementById(id);
const statusLabels = {pending_review: 'À vérifier', validated: 'Validée', paid: 'Réglée'};
const providerLabels = {demo: 'Exemples sans LLM', anthropic: 'Claude · extraction IA', ollama: 'Ollama · extraction IA'};
const evidenceLabels = {supplier_name:'Fournisseur',invoice_number:'Numéro de facture',invoice_date:'Date',subtotal_ht:'Total HT',tax_amount:'Taxes',total_ttc:'Total TTC'};
const editableFields = ['supplier_name','supplier_ice','invoice_number','invoice_date','due_date','currency','subtotal_ht','tax_amount','total_ttc','category','description','notes'];
const amountFields = ['subtotal_ht','tax_amount','total_ttc'];
const reviewDialog = $('review-dialog');
const settingsDialog = $('settings-dialog');
const form = $('invoice-form');
let config = null;
let currentInvoice = null;
let listController = null;
let searchTimer = null;
let busy = false;
let previousFocus = null;

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = String(content);
  return node;
}
function message(id, text, kind = '') {
  const target = $(id);
  target.textContent = text || '';
  target.className = `message ${kind}`;
  target.hidden = !text;
}
function money(value, currency = 'MAD') {
  if (value === null || value === undefined || value === '') return 'Non renseigné';
  const number = Number(value);
  if (!Number.isFinite(number)) return 'À vérifier';
  return `${new Intl.NumberFormat('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(number)} ${currency || '—'}`;
}
function date(value) {
  if (!value) return 'Non renseignée';
  const parsed = new Date(`${value}T12:00:00`);
  return Number.isNaN(parsed.valueOf()) ? String(value) : new Intl.DateTimeFormat('fr-FR', {day:'2-digit',month:'short',year:'numeric'}).format(parsed);
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    let detail = body?.detail;
    if (Array.isArray(detail)) detail = detail.map(item => item.msg || 'Donnée invalide').join(' ; ');
    if (typeof detail !== 'string') detail = 'Le serveur n’a pas pu traiter cette demande.';
    const error = new Error(detail);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}
function friendlyError(error) {
  if (error instanceof TypeError) return 'Impossible de joindre le serveur. Vérifiez que l’application est démarrée, puis réessayez.';
  return error.message || 'Une erreur est survenue. Réessayez dans un instant.';
}
function tableState(title, text) {
  const state = $('table-state');
  state.replaceChildren(el('span','empty-icon','▤'),el('h3','',title),el('p','',text));
  state.hidden = false;
}
function makeStatus(status) { return el('span',`status ${statusLabels[status] ? status : 'pending_review'}`,statusLabels[status] || 'À vérifier'); }
function setKpi(id,value,isMoney=false) {
  const node = $(id);
  if (!isMoney) {node.textContent = value ?? '0'; return;}
  node.replaceChildren(document.createTextNode(money(value).replace(/ MAD$/,'')),el('span','currency-small',' MAD'));
}
function renderList(data) {
  const items = Array.isArray(data.items) ? data.items : [];
  const summary = data.summary || {};
  setKpi('kpi-total',summary.total_mad,true);
  setKpi('kpi-unpaid',summary.unpaid_mad,true);
  setKpi('kpi-review',summary.pending_review);
  setKpi('kpi-overdue',summary.overdue_count);
  $('nav-count').textContent = summary.invoice_count ?? 0;
  $('kpi-total-caption').textContent = 'Factures en MAD, y compris à vérifier';
  $('result-count').textContent = items.length;
  $('invoice-rows').replaceChildren();
  $('table-state').hidden = items.length > 0;
  if (!items.length) {
    const filtered = $('search').value || $('status-filter').value || $('category-filter').value;
    tableState(filtered ? 'Aucune facture ne correspond' : 'Votre première facture commence ici',filtered ? 'Modifiez votre recherche ou vos filtres pour retrouver les factures.' : 'Importez un document ou essayez les trois exemples fictifs pour découvrir la vérification.');
  }
  items.forEach(invoice => {
    const row = el('tr');
    const supplier = el('td');
    const cell = el('div','supplier-cell');
    const name = invoice.supplier_name || 'Fournisseur à identifier';
    const initials = name.split(/\s+/).slice(0,2).map(s => s.charAt(0)).join('').toUpperCase();
    const avatar = el('span','supplier-avatar',initials);avatar.setAttribute('aria-hidden','true');
    const detail = el('div');detail.append(el('strong','',name),el('small','',invoice.invoice_number || 'Numéro à renseigner'));
    cell.append(avatar,detail);supplier.append(cell);
    const dateCell = el('td','cell-muted',date(invoice.invoice_date));
    if (invoice.overdue) dateCell.append(el('span','overdue','Échéance dépassée'));
    const category = el('td');category.append(el('span','category-tag',invoice.category || 'À classer'));
    const amount = el('td','amount-cell',money(invoice.total_ttc,invoice.currency));
    const status = el('td');status.append(makeStatus(invoice.status));
    const action = el('td');const button = el('button','open-row','→');button.type='button';button.disabled=busy;button.setAttribute('aria-label',`Ouvrir la facture ${invoice.invoice_number || ''} de ${name}`);button.addEventListener('click',()=>openInvoice(invoice.id));action.append(button);
    row.append(supplier,dateCell,category,amount,status,action);$('invoice-rows').append(row);
  });
  const otherCurrencies = [...new Set(items.map(i=>i.currency).filter(c=>c && c !== 'MAD'))];
  $('table-caption').textContent = otherCurrencies.length ? `Autres devises affichées séparément : ${otherCurrencies.join(', ')}. Les indicateurs totalisent uniquement le MAD.` : 'Les indicateurs de montant totalisent uniquement les factures en MAD.';
  renderSuppliers(Array.isArray(data.suppliers) ? data.suppliers : []);
}
function renderSuppliers(suppliers) {
  const list=$('supplier-list');list.replaceChildren();
  $('supplier-count').textContent=suppliers.length;
  if(!suppliers.length){list.append(el('p','supplier-empty','Validez une facture pour alimenter le référentiel.'));return;}
  suppliers.forEach(supplier=>{
    const card=el('article','supplier-card');
    const info=el('div');info.append(el('strong','',supplier.name || 'Fournisseur confirmé'));
    info.append(el('small','',supplier.ice ? `ICE : ${supplier.ice}` : 'ICE non renseigné'));
    const count=Number(supplier.invoice_count) || 0;
    card.append(info,el('span','supplier-invoice-count',`${count} facture${count>1?'s':''} confirmée${count>1?'s':''}`));
    list.append(card);
  });
}
async function loadInvoices() {
  listController?.abort();listController = new AbortController();
  const params = new URLSearchParams();
  if ($('search').value.trim()) params.set('search',$('search').value.trim());
  if ($('status-filter').value) params.set('status',$('status-filter').value);
  if ($('category-filter').value) params.set('category',$('category-filter').value);
  $('invoice-rows').classList.add('loading-row');
  try {const data = await api(`/api/invoices?${params}`,{signal:listController.signal});renderList(data);}
  catch(error) {if(error.name !== 'AbortError'){message('global-message',friendlyError(error),'error');if(!$('invoice-rows').children.length)tableState('Chargement impossible','Le serveur doit être accessible pour consulter vos factures. Utilisez Actualiser pour réessayer.');}}
  finally {$('invoice-rows').classList.remove('loading-row');}
}
async function loadConfig() {
  try {
    config = await api('/api/config');
    $('mode-label').textContent = config.demo ? 'Mode démonstration' : (config.configured ? providerLabels[config.provider] || 'Extraction IA' : 'Extraction à configurer');
    $('config-provider').textContent = config.demo ? 'Démonstration · données fictives' : providerLabels[config.provider] || config.provider;
    $('config-model').textContent = config.demo ? 'Trois exemples reconnus, sans appel à un modèle.' : `Modèle : ${config.model || 'non renseigné'}`;
    $('config-status').className = `status ${config.configured || config.demo ? 'validated' : 'pending_review'}`;
    $('config-status').textContent = config.configured || config.demo ? 'Prêt à utiliser' : 'Configuration requise';
    $('config-explanation').textContent = config.demo ? 'Ce mode vous permet de découvrir le parcours complet avec trois factures fictives. Pour vos propres scans, connectez un modèle dans la configuration du serveur.' : 'Les documents importés sont analysés par le modèle choisi sur le serveur. Les données restent à vérifier avant validation.';
    $('demo-button').hidden = !config.demo;
  } catch(error) {$('mode-label').textContent = 'Serveur indisponible';$('config-provider').textContent = 'Connexion indisponible';$('config-explanation').textContent = friendlyError(error);}
}
function setBusy(value) {
  busy = value;
  ['upload-button','camera-button','demo-button','save-button','approve-button','paid-button','settings-button','mode-button'].forEach(id=>$(id).disabled=value);
  editableFields.forEach(name=>form.elements[name].disabled=value || currentInvoice?.status==='paid');
  document.querySelectorAll('.open-row').forEach(button=>button.disabled=value);
  reviewDialog.setAttribute('aria-busy',String(value));
}
function showDialog(dialog) {
  previousFocus = document.activeElement;
  if (!dialog.open) dialog.showModal();
}
function closeDialog(dialog) {
  if (busy && dialog === reviewDialog) return;
  dialog.close();
  if (previousFocus?.isConnected) previousFocus.focus();
}
function renderDocument(invoice) {
  const preview = $('document-preview');preview.replaceChildren();
  const fallback = `/api/invoices/${encodeURIComponent(invoice.id)}/document`;
  let url = fallback;
  try { const candidate = new URL(invoice.document_url || fallback,location.origin);if(candidate.origin === location.origin && candidate.pathname.startsWith('/api/invoices/'))url=candidate.pathname+candidate.search; } catch {}
  $('document-link').href=url;
  if (/\.(jpg|jpeg|png)$/i.test(invoice.filename || '')) {const img=el('img');img.src=url;img.alt=`Document original : ${invoice.filename || 'facture'}`;preview.append(img);}
  else {const frame=el('iframe');frame.src=url;frame.title=`Document original : ${invoice.filename || 'facture'}`;preview.append(frame);}
}
function cents(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const clean=String(value).trim().replace(/\s/g,'').replace(',','.');
  if(!/^\d+(?:\.\d{1,2})?$/.test(clean))return null;
  const parts=clean.split('.');
  try{return BigInt(parts[0])*100n+BigInt((parts[1] || '').padEnd(2,'0'));}catch{return null;}
}
function localWarnings() {
  const notes=[];
  ['supplier_name','invoice_number','invoice_date','currency',...amountFields].forEach(name=>{if(!form.elements[name].value.trim())notes.push(`À renseigner : ${evidenceLabels[name] || (name === 'currency' ? 'devise' : name)}.`);});
  const values=amountFields.map(n=>cents(form.elements[n].value));
  amountFields.forEach((name,index)=>{if(form.elements[name].value && values[index] === null)notes.push(`${evidenceLabels[name]} : utilisez un montant positif avec deux décimales maximum.`);});
  if(values.every(v=>v !== null)){const difference=values[0]+values[1]-values[2];if(difference > 1n || difference < -1n)notes.push('Les montants ne concordent pas : HT + taxes doit être égal au TTC.');}
  const invoiceDate=form.elements.invoice_date.value,dueDate=form.elements.due_date.value;
  if(invoiceDate && dueDate && dueDate<invoiceDate)notes.push('L’échéance est antérieure à la date de facture.');
  if(form.elements.currency.value && !/^[A-Z]{3}$/.test(form.elements.currency.value.trim().toUpperCase()))notes.push('La devise doit comporter trois lettres, par exemple MAD.');
  return notes;
}
function renderWarnings(extra=[]) {
  const extraction=[...new Set(currentInvoice?.warnings || [])];
  const validation=[...new Set([...localWarnings(),...extra])];
  const box=$('review-warnings');box.replaceChildren();box.hidden=!(extraction.length+validation.length);
  [[extraction,'Alertes à l’extraction · conservées pour traçabilité'],[validation,'Contrôles avant validation']].forEach(([warnings,title])=>{
    if(!warnings.length)return;
    box.append(el('strong','',title));
    const list=el('ul');warnings.forEach(warning=>list.append(el('li','',warning)));box.append(list);
  });
}
function renderInvoice(invoice) {
  currentInvoice=invoice;
  $('review-title').textContent=invoice.invoice_number ? `Facture ${invoice.invoice_number}` : 'Vérifier la facture';
  $('review-subtitle').textContent=invoice.filename || 'Document importé';
  $('review-status').className=`status ${invoice.status}`;$('review-status').textContent=statusLabels[invoice.status] || 'À vérifier';
  $('review-provider').textContent=providerLabels[invoice.provider] || 'Extraction';
  editableFields.forEach(name=>{const field=form.elements[name];let value=invoice[name] ?? '';if(amountFields.includes(name))value=String(value).replace('.',',');field.value=value;field.disabled=busy || invoice.status==='paid';});
  $('save-button').hidden=invoice.status==='paid';
  $('approve-button').hidden=invoice.status!=='pending_review';
  $('paid-button').hidden=invoice.status!=='validated';
  $('review-footer-note').textContent=invoice.status==='paid' ? 'Cette facture réglée est conservée en lecture seule.' : invoice.status==='validated' ? 'Une correction remet la facture en attente de validation.' : 'Votre validation confirme les informations pour l’agence.';
  renderDocument(invoice);renderWarnings();
  const evidence=$('evidence-list');evidence.replaceChildren();
  const entries=Object.entries(invoice.evidence || {}).filter(([,value])=>value !== null && value !== '');
  if(!entries.length){evidence.append(el('dd','','Aucun extrait détaillé fourni par le modèle.'));}
  else entries.forEach(([key,value])=>{evidence.append(el('dt','',evidenceLabels[key] || key),el('dd','',value));});
}
async function openInvoice(id, force=false) {
  if(busy && !force)return;
  setBusy(true);
  message('global-message','Ouverture de la facture…','loading');
  try{const invoice=await api(`/api/invoices/${encodeURIComponent(id)}`);message('global-message','');message('review-message','');renderInvoice(invoice);showDialog(reviewDialog);$('close-review').focus();}
  catch(error){message('global-message',friendlyError(error),'error');}
  finally{setBusy(false);}
}
async function upload(file) {
  if(!file)return;
  const limit=(config?.max_upload_mb || 10)*1024*1024;
  if(file.size>limit){message('global-message',`Le document dépasse ${config?.max_upload_mb || 10} Mo. Utilisez un fichier plus léger.`,'error');return;}
  setBusy(true);message('global-message','Import et extraction en cours… Cela peut prendre un instant.','loading');
  try {const body=new FormData();body.append('file',file);const invoice=await api('/api/invoices/upload',{method:'POST',body});await loadInvoices();message('global-message','Document importé. Vérifiez les informations avant de valider.');message('review-message','');renderInvoice(invoice);showDialog(reviewDialog);$('close-review').focus();}
  catch(error){if(error.status===409 && error.body?.existing_id){message('global-message','Ce document a déjà été importé. Ouverture de la facture existante.');await openInvoice(error.body.existing_id,true);}else message('global-message',friendlyError(error),'error');}
  finally{setBusy(false);$('file-input').value='';$('camera-input').value='';}
}
function collectChanges() {
  const changes={};
  editableFields.forEach(name=>{let value=form.elements[name].value.trim();if(name==='currency')value=value.toUpperCase();if(amountFields.includes(name))value=value.replace(/\s/g,'').replace(',','.');if(value==='')value=['description','notes'].includes(name)?'':null;
    let previous=currentInvoice[name] ?? null;if(['description','notes'].includes(name))previous=previous ?? '';if(amountFields.includes(name) && value!==null && previous!==null){const one=cents(value),two=cents(previous);if(one !== null && two !== null && one===two)return;}
    if(value !== previous)changes[name]=value;
  });
  return changes;
}
async function saveChanges() {
  const changes=collectChanges();
  if(!Object.keys(changes).length)return currentInvoice;
  return api(`/api/invoices/${encodeURIComponent(currentInvoice.id)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)});
}
async function performAction(action) {
  if(!currentInvoice || busy)return;
  setBusy(true);message('review-message',action==='approve'?'Validation en cours…':action==='payment'?'Enregistrement du règlement…':'Enregistrement…','loading');
  try {
    let updated;
    if(action==='payment') {
      if(Object.keys(collectChanges()).length){message('review-message','Enregistrez vos corrections, puis validez à nouveau la facture avant de la marquer comme réglée.','error');return;}
      updated=await api(`/api/invoices/${encodeURIComponent(currentInvoice.id)}/payment`,{method:'POST'});
    } else {
      updated=await saveChanges();
      if(action==='approve')updated=await api(`/api/invoices/${encodeURIComponent(updated.id)}/approve`,{method:'POST'});
    }
    renderInvoice(updated);await loadInvoices();
    message('review-message',action==='approve'?'Facture validée. Le fournisseur est ajouté au référentiel de l’agence.':action==='payment'?'Facture marquée comme réglée.':'Corrections enregistrées.');
  } catch(error) {
    message('review-message',friendlyError(error),'error');
    renderWarnings(Array.isArray(error.body?.errors)?error.body.errors:[]);
    // A correction may have saved successfully before approval was refused.
    try{const refreshed=await api(`/api/invoices/${encodeURIComponent(currentInvoice.id)}`);currentInvoice=refreshed;await loadInvoices();}catch{}
  } finally{setBusy(false);}
}
$('upload-button').addEventListener('click',()=>$('file-input').click());
$('camera-button').addEventListener('click',()=>$('camera-input').click());
$('file-input').addEventListener('change',event=>upload(event.target.files[0]));
$('camera-input').addEventListener('change',event=>upload(event.target.files[0]));
$('demo-button').addEventListener('click',async()=>{
  if(busy)return;setBusy(true);message('global-message','Préparation des exemples fictifs…','loading');
  try{const data=await api('/api/demo',{method:'POST'});$('search').value='';$('status-filter').value='';$('category-filter').value='';await loadInvoices();message('global-message',data.message || 'Les exemples sont prêts. Ouvrez une facture pour vérifier les données extraites.');}
  catch(error){message('global-message',friendlyError(error),'error');}finally{setBusy(false);}
});
$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadInvoices,250);});
['status-filter','category-filter'].forEach(id=>$(id).addEventListener('change',loadInvoices));
$('refresh-button').addEventListener('click',()=>{message('global-message','');loadInvoices();loadConfig();});
$('close-review').addEventListener('click',()=>closeDialog(reviewDialog));
$('close-settings').addEventListener('click',()=>closeDialog(settingsDialog));
['settings-button','mode-button'].forEach(id=>$(id).addEventListener('click',()=>{if(busy)return;loadConfig();showDialog(settingsDialog);$('close-settings').focus();}));
reviewDialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
reviewDialog.addEventListener('close',()=>{if(previousFocus?.isConnected)previousFocus.focus();});
settingsDialog.addEventListener('close',()=>{if(previousFocus?.isConnected)previousFocus.focus();});
form.addEventListener('input',()=>renderWarnings());
form.addEventListener('submit',event=>{event.preventDefault();performAction('save');});
$('approve-button').addEventListener('click',()=>performAction('approve'));
$('paid-button').addEventListener('click',()=>performAction('payment'));
Promise.all([loadConfig(),loadInvoices()]);
