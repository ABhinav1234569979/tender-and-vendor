import { useEffect, useMemo, useRef, useState } from 'react'
import {
  API_BASE,
  downloadAllReports,
  downloadReport,
  downloadVendorReport,
  getFiles,
  getOllamaStatus,
  getOutputFiles,
  getResults,
  getRuns,
  getStatus,
  getSummary,
  resetPipeline,
  runPipeline,
  uploadFiles,
} from './api'

/* ─── helpers ───────────────────────────────────────────────────────────── */
function fmtElapsed(ms) {
  if (ms < 1000) return `${ms}ms`
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function fmtSize(bytes = 0) {
  const n = Number(bytes) || 0
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function fmtDate(value = '') {
  if (!value) return ''
  return String(value).slice(0, 16).replace('T', ' ')
}

function normalizeVerdict(value = '') {
  return String(value || '').toLowerCase().replace(/\s+/g, '-')
}

function StatusBadge({ status }) {
  const map = {
    idle:      { label: 'Idle',      cls: 'badge-idle' },
    queued:    { label: 'Queued',    cls: 'badge-queued' },
    running:   { label: 'Running',   cls: 'badge-running' },
    completed: { label: 'Completed', cls: 'badge-done' },
    failed:    { label: 'Failed',    cls: 'badge-fail' },
    unknown:   { label: 'Unknown',   cls: 'badge-idle' },
  }
  const { label, cls } = map[status] ?? map.unknown
  return <span className={`status-badge ${cls}`}>{label}</span>
}

function ProgressBar({ value, status }) {
  const pct = Math.min(100, Math.max(0, Number(value) || 0))
  const cls =
    status === 'completed' ? 'bar-fill bar-done' :
    status === 'failed'    ? 'bar-fill bar-fail' :
    status === 'running'   ? 'bar-fill bar-running' :
                             'bar-fill bar-idle'
  return (
    <div className="progress-track" role="progressbar"
      aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className={cls} style={{ width: `${pct}%` }} />
      <span className="progress-label">{pct.toFixed(1)}%</span>
    </div>
  )
}

/* ─── main component ────────────────────────────────────────────────────── */
export default function App() {
  const [masterFile, setMasterFile] = useState(null)
  const [vendorFiles, setVendorFiles] = useState([])
  const [files, setFiles] = useState([])
  const [outputFiles, setOutputFiles] = useState([])
  const [summary, setSummary] = useState(null)
  const [results, setResults] = useState([])
  const [runHistory, setRunHistory] = useState([])
  const [ollamaStatus, setOllamaStatus] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('')
  const [runStatus, setRunStatus] = useState('idle')
  const [runProgress, setRunProgress] = useState(0)
  const [runMessage, setRunMessage] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [activeDoc, setActiveDoc] = useState(null)
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      text: 'Document assistant shell ready. I can summarize loaded files and pipeline results here. Real document Q&A stays disabled until the LM Studio/backend chat endpoint is available.',
    },
  ])

  const startTimeRef = useRef(null)
  const elapsedTimerRef = useRef(null)
  const selectedCount = useMemo(() => vendorFiles.filter(Boolean).length, [vendorFiles])
  const isActive = ['queued', 'running'].includes(runStatus)

  const sidebarDocs = useMemo(() => {
    const selectedTender = masterFile ? [{
      id: 'selected-master',
      group: 'Tender document',
      label: 'Selected tender workbook',
      name: masterFile.name,
      meta: `${fmtSize(masterFile.size)} · ready to upload`,
      type: 'selected-master',
      file: masterFile,
      action: 'open-local',
    }] : []

    const selectedVendors = vendorFiles.filter(Boolean).map((file, index) => ({
      id: `selected-vendor-${index}`,
      group: 'Vendor documents',
      label: `Selected vendor ${index + 1}`,
      name: file.name,
      meta: `${fmtSize(file.size)} · ready to upload`,
      type: 'selected-vendor',
      file,
      action: 'open-local',
    }))

    const uploadedTender = files
      .filter((file) => file.role === 'master_workbook' || file.file_name.toLowerCase().endsWith('.xlsx'))
      .map((file) => ({
        id: `incoming-${file.file_name}`,
        group: 'Tender document',
        label: 'Uploaded tender workbook',
        name: file.file_name,
        meta: `${fmtSize(file.size_bytes)} · stored on backend`,
        type: 'incoming-master',
        source: file,
        action: 'stored-only',
      }))

    const uploadedVendors = files
      .filter((file) => file.role === 'vendor_pdf' || file.file_name.toLowerCase().endsWith('.pdf'))
      .map((file) => ({
        id: `incoming-${file.file_name}`,
        group: 'Vendor documents',
        label: 'Uploaded vendor PDF',
        name: file.file_name,
        meta: `${fmtSize(file.size_bytes)} · stored on backend`,
        type: 'incoming-vendor',
        source: file,
        action: 'open-pdf',
      }))

    const reports = outputFiles.map((file) => ({
      id: `output-${file.file_name}`,
      group: 'Merged / reports',
      label: file.file_name === 'vendor_comparison_matrix.xlsx' ? 'Merged comparison matrix' : 'Vendor report',
      name: file.file_name,
      meta: `${fmtSize(file.size_bytes)} · ${fmtDate(file.modified_at)}`,
      type: 'output-report',
      source: file,
      action: 'download-report',
    }))

    return [...selectedTender, ...uploadedTender, ...selectedVendors, ...uploadedVendors, ...reports]
  }, [masterFile, vendorFiles, files, outputFiles])

  const groupedDocs = useMemo(() => {
    const groups = {
      'Tender document': [],
      'Vendor documents': [],
      'Merged / reports': [],
    }
    for (const doc of sidebarDocs) groups[doc.group]?.push(doc)
    return groups
  }, [sidebarDocs])

  useEffect(() => {
    if (!activeDoc && sidebarDocs.length) setActiveDoc(sidebarDocs[0])
    if (activeDoc && !sidebarDocs.some((doc) => doc.id === activeDoc.id) && sidebarDocs.length) {
      setActiveDoc(sidebarDocs[0])
    }
  }, [activeDoc, sidebarDocs])

  /* elapsed wall-clock timer — runs whenever pipeline is active */
  useEffect(() => {
    if (isActive) {
      if (!startTimeRef.current) startTimeRef.current = Date.now()
      elapsedTimerRef.current = window.setInterval(
        () => setElapsed(Date.now() - startTimeRef.current), 500)
    } else {
      window.clearInterval(elapsedTimerRef.current)
      // keep final elapsed visible after completion/failure
    }
    return () => window.clearInterval(elapsedTimerRef.current)
  }, [isActive])

  /* poll pipeline status every 1.5 s whenever we have a runId */
  useEffect(() => {
    if (!runId) return undefined
    const poll = window.setInterval(async () => {
      try {
        const p = await getStatus(runId)
        const newStatus = p.status || 'unknown'
        setRunStatus(newStatus)
        setRunProgress(Number(p.progress || 0))
        setRunMessage(p.message || p.error || '')
        if (newStatus === 'completed') {
          await refreshDashboard()
          window.clearInterval(poll)
        }
        if (newStatus === 'failed') {
          refreshRunHistory()
          window.clearInterval(poll)
        }
      } catch (e) { setError(e.message) }
    }, 1500)
    return () => window.clearInterval(poll)
  }, [runId])

  useEffect(() => { refreshDashboard() }, [])

  async function refreshDashboard() {
    try {
      const [fp, sp, rp, op, os] = await Promise.all([
        getFiles(), getSummary(), getResults({ limit: 10 }), getOutputFiles(), getOllamaStatus(),
      ])
      setFiles(fp.incoming || [])
      setSummary(sp)
      setResults(rp.results || [])
      setOutputFiles(op.files || [])
      setOllamaStatus(os)
      refreshRunHistory()
    } catch (_) {}
  }

  async function refreshRunHistory() {
    try {
      const p = await getRuns({ limit: 8 })
      setRunHistory(Array.isArray(p) ? p : [])
    } catch (_) {}
  }

  /* file helpers */
  function addVendorRow() { setVendorFiles(c => [...c, null]) }

  function handleMasterChange(file) {
    setMasterFile(file)
    if (file) {
      setActiveDoc({
        id: 'selected-master',
        group: 'Tender document',
        label: 'Selected tender workbook',
        name: file.name,
        meta: `${fmtSize(file.size)} · ready to upload`,
        type: 'selected-master',
        file,
        action: 'open-local',
      })
    }
  }

  function updateVendorFile(i, f) {
    setVendorFiles(c => c.map((e, p) => p === i ? f : e))
    if (f) {
      setActiveDoc({
        id: `selected-vendor-${i}`,
        group: 'Vendor documents',
        label: `Selected vendor ${i + 1}`,
        name: f.name,
        meta: `${fmtSize(f.size)} · ready to upload`,
        type: 'selected-vendor',
        file: f,
        action: 'open-local',
      })
    }
  }

  function removeVendorRow(i) { setVendorFiles(c => c.filter((_, p) => p !== i)) }

  /* actions */
  async function handleUpload() {
    setError(''); setMessage('')
    if (!masterFile) return setError('Choose one .xlsx master workbook first.')
    if (!selectedCount) return setError('Add at least one vendor PDF.')
    setBusy(true)
    try {
      const p = await uploadFiles([masterFile, ...vendorFiles.filter(Boolean)])
      setMessage(`Uploaded ${p.saved.length} file(s).`)
      await refreshDashboard()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleRunPipeline() {
    setError(''); setMessage(''); setBusy(true)
    try {
      const p = await runPipeline()
      setRunId(p.run_id)
      setRunStatus(p.status || 'queued')
      setRunProgress(0); setRunMessage('Queued')
      startTimeRef.current = Date.now(); setElapsed(0)
      setMessage('Pipeline started.')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleResetPipeline() {
    setError(''); setMessage(''); setBusy(true)
    try {
      const p = await resetPipeline()
      setMessage(`Pipeline reset. Cleared ${p.cleared} stuck run(s).`)
      setRunStatus('idle'); setRunId(''); setRunProgress(0); setRunMessage('')
      startTimeRef.current = null; setElapsed(0)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  function _dl(blob, filename) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
  }

  async function handleDownloadReport() {
    setError(''); setMessage(''); setBusy(true)
    try { _dl(await downloadReport(), 'vendor_comparison_matrix.xlsx'); setMessage('Download started.') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleDownloadAll() {
    setError(''); setMessage(''); setBusy(true)
    try { _dl(await downloadAllReports(), 'compliance_reports.zip'); setMessage('All reports downloaded as ZIP.') }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function handleDownloadVendor(vendorId) {
    setError(''); setMessage(''); setBusy(true)
    try { _dl(await downloadVendorReport(vendorId), `vendor_${vendorId}.xlsx`); setMessage(`Downloaded vendor_${vendorId}.xlsx`) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  function openLocalFile(file) {
    if (!file) return
    const url = URL.createObjectURL(file)
    window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 20000)
  }

  async function handleDocumentAction(doc = activeDoc) {
    if (!doc) return
    setActiveDoc(doc)
    setError(''); setMessage('')

    if (doc.action === 'open-local') {
      openLocalFile(doc.file)
      return
    }

    if (doc.action === 'open-pdf') {
      window.open(`${API_BASE}/pdf/${encodeURIComponent(doc.name)}`, '_blank', 'noopener,noreferrer')
      return
    }

    if (doc.action === 'download-report') {
      const name = doc.name || ''
      const isVendor = name.startsWith('vendor_') && name !== 'vendor_comparison_matrix.xlsx'
      if (isVendor) {
        const vendorId = name.replace(/^vendor_/, '').replace(/\.xlsx$/, '')
        await handleDownloadVendor(vendorId)
      } else {
        await handleDownloadReport()
      }
      return
    }

    setMessage('This file is stored on the backend. Preview/download for uploaded Excel files needs a backend endpoint later.')
  }

  function createChatReply(question) {
    const q = question.toLowerCase()
    const docName = activeDoc?.name ? ` Current sidebar selection: ${activeDoc.name}.` : ''

    if (q.includes('file') || q.includes('document') || q.includes('doc')) {
      const fileNames = sidebarDocs.map((doc) => `• ${doc.group}: ${doc.name}`).join('\n')
      return fileNames
        ? `Loaded document index:\n${fileNames}${docName}`
        : 'No documents are loaded yet. Choose a tender workbook and at least one vendor PDF first.'
    }

    if (q.includes('summary') || q.includes('result') || q.includes('score') || q.includes('status')) {
      const counts = Object.entries(summary?.status_counts || {})
        .map(([status, count]) => `${status}: ${count}`)
        .join(', ')
      const latest = results.slice(0, 5)
        .map((row) => `${row.spec_id} / ${row.vendor_id}: ${row.status}`)
        .join('\n')
      return `Pipeline status: ${runStatus}. Total results: ${summary?.total_results ?? 0}. ${counts ? `Breakdown: ${counts}.` : 'No status breakdown yet.'}${latest ? `\nLatest rows:\n${latest}` : ''}`
    }

    if (q.includes('llm') || q.includes('model') || q.includes('lm studio')) {
      return ollamaStatus?.healthy
        ? `LLM backend is reachable at ${ollamaStatus.host}. Selected model: ${ollamaStatus.selected_model || ollamaStatus.models?.[0] || 'not specified'}.`
        : `LLM backend is offline from this laptop. The UI can still show files, results, and reports, but real document Q&A needs the backend chat endpoint plus LM Studio access.${docName}`
    }

    if (q.includes('vendor') || q.includes('tender') || q.includes('requirement') || q.includes('compliance')) {
      return `I can show the selected documents and latest compliance rows, but I am not doing semantic document Q&A yet. That final part needs a backend /document-chat endpoint wired to LM Studio. For now, use the Latest Results panel and downloaded matrix for evidence.${docName}`
    }

    return `Frontend chat shell is working. Real answers about document content are intentionally disabled until the backend/LLM handoff is ready.${docName}`
  }

  function handleChatSend(e) {
    e.preventDefault()
    const text = chatInput.trim()
    if (!text) return
    const userMessage = { id: `u-${Date.now()}`, role: 'user', text }
    const assistantMessage = { id: `a-${Date.now()}`, role: 'assistant', text: createChatReply(text) }
    setChatMessages((current) => [...current, userMessage, assistantMessage])
    setChatInput('')
  }

  /* derive human phase label from raw backend message */
  function phaseLabel() {
    const m = (runMessage || '').toLowerCase()
    if (!m) return ''
    if (m.includes('loaded') && m.includes('specs'))    return `Phase 0 — ${runMessage}`
    if (m.includes('parsing pdf'))                       return `Phase 1 — ${runMessage}`
    if (m.includes('parsed'))                            return `Phase 1 — ${runMessage}`
    if (m.includes('evaluating pair'))                   return `Phase 2 — ${runMessage}`
    if (m.includes('evaluated'))                         return `Phase 2 — ${runMessage}`
    if (m.includes('skipped') && m.includes('cached'))  return `Phase 2 — ${runMessage}`
    if (m.includes('building') || m.includes('report')) return `Phase 3 — ${runMessage}`
    if (m.includes('completed'))                         return `✓ ${runMessage}`
    if (m.includes('failed'))                            return `✗ ${runMessage}`
    if (m.includes('queue'))                             return 'Queued — waiting to start'
    return runMessage
  }

  function renderDocumentGroup(title, docs) {
    return (
      <div className="doc-group" key={title}>
        <div className="doc-group__title">{title}</div>
        {docs.length ? docs.map((doc) => (
          <button
            key={doc.id}
            type="button"
            className={`doc-card ${activeDoc?.id === doc.id ? 'doc-card--active' : ''}`}
            onClick={() => setActiveDoc(doc)}
          >
            <span className="doc-card__label">{doc.label}</span>
            <strong>{doc.name}</strong>
            <span>{doc.meta}</span>
          </button>
        )) : <div className="doc-empty">Not loaded yet</div>}
      </div>
    )
  }

  /* ── render ── */
  return (
    <div className="app-shell">
      <div className="app-frame">
        <aside className="document-sidebar" aria-label="Document workspace">
          <div className="sidebar-header">
            <p className="eyebrow">Workspace</p>
            <h2>Document Dock</h2>
            <p>Quick access to tender, vendor, and merged output files.</p>
          </div>

          <div className="sidebar-stats">
            <div><span>Selected</span><strong>{selectedCount + (masterFile ? 1 : 0)}</strong></div>
            <div><span>Uploaded</span><strong>{files.length}</strong></div>
            <div><span>Reports</span><strong>{outputFiles.length}</strong></div>
          </div>

          <div className="doc-groups">
            {Object.entries(groupedDocs).map(([title, docs]) => renderDocumentGroup(title, docs))}
          </div>

          <div className="active-doc-panel">
            <span className="panel-kicker">Selected</span>
            {activeDoc ? (
              <>
                <strong>{activeDoc.name}</strong>
                <p>{activeDoc.label} · {activeDoc.meta}</p>
                <button className="sidebar-action" type="button" onClick={() => handleDocumentAction(activeDoc)} disabled={busy}>
                  {activeDoc.action === 'stored-only' ? 'Backend stored' : activeDoc.action === 'open-pdf' ? 'Open PDF' : activeDoc.action === 'download-report' ? 'Download' : 'Open'}
                </button>
              </>
            ) : (
              <p>No active document selected.</p>
            )}
          </div>

          <div className="doc-chat">
            <div className="doc-chat__head">
              <div>
                <span className="panel-kicker">Ask</span>
                <strong>Document Chat</strong>
              </div>
              <span className={`chat-status ${ollamaStatus?.healthy ? 'chat-status--ok' : 'chat-status--offline'}`}>
                {ollamaStatus?.healthy ? 'LLM ready' : 'LLM offline'}
              </span>
            </div>
            <div className="chat-messages">
              {chatMessages.map((msg) => (
                <div className={`chat-bubble chat-bubble--${msg.role}`} key={msg.id}>
                  {msg.text.split('\n').map((line, index) => (
                    <p key={`${msg.id}-${index}`}>{line}</p>
                  ))}
                </div>
              ))}
            </div>
            <form className="chat-form" onSubmit={handleChatSend}>
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder="Ask about files, summary, LLM status..."
              />
              <button type="submit" disabled={!chatInput.trim()}>Send</button>
            </form>
          </div>
        </aside>

        <main className="workspace">

          {/* topbar */}
          <header className="topbar">
            <div>
              <p className="eyebrow">Tender &amp; Vendor Compliance</p>
              <h1>Compliance Pipeline Console</h1>
              <p className="topbar-subtitle">Local-first review dashboard for synthetic tender/vendor testing.</p>
            </div>
            <div className="topbar-right">
              {ollamaStatus && (
                <div className={`ollama-chip ${ollamaStatus.healthy ? 'ollama-ok' : 'ollama-down'}`}
                  title={ollamaStatus.healthy ? `Models: ${ollamaStatus.models.join(', ')}` : 'LLM server not reachable — using heuristic fallback'}>
                  <span className="ollama-dot" />
                  {ollamaStatus.healthy
                    ? `LLM · ${ollamaStatus.selected_model || ollamaStatus.models[0] || 'ready'}`
                    : 'LLM offline'}
                </div>
              )}
              <div className="api-chip">{API_BASE}</div>
            </div>
          </header>

          {/* ── pipeline progress card ── */}
          <section className="pipeline-card" aria-label="Pipeline status">
            <div className="pipeline-card__header">
              <div className="pipeline-card__title">
                <span className="pipeline-card__label">Pipeline</span>
                <StatusBadge status={runStatus} />
              </div>
              <div className="pipeline-card__meta">
                {elapsed > 0 && (
                  <span className="pipeline-card__elapsed">⏱ {fmtElapsed(elapsed)}</span>
                )}
                <button className="plain-button compact-button" type="button"
                  onClick={refreshDashboard} disabled={busy}>Refresh</button>
              </div>
            </div>

            <ProgressBar value={runProgress} status={runStatus} />

            {phaseLabel() && (
              <p className="pipeline-card__phase">{phaseLabel()}</p>
            )}

            {/* step indicators */}
            <div className="pipeline-steps">
              {[
                { key: 'upload',   label: 'Upload',   done: files.length > 0 },
                { key: 'parse',    label: 'Parse',    done: runProgress > 5 },
                { key: 'evaluate', label: 'Evaluate', done: runProgress > 50 },
                { key: 'report',   label: 'Report',   done: runStatus === 'completed' },
              ].map((step, i) => (
                <div key={step.key}
                  className={`pipeline-step ${step.done ? 'step-done' : isActive ? 'step-active' : 'step-pending'}`}>
                  <div className="step-dot">{step.done ? '✓' : i + 1}</div>
                  <span className="step-label">{step.label}</span>
                </div>
              ))}
            </div>

            {runId && (
              <p className="pipeline-card__runid">Run ID: <code>{runId}</code></p>
            )}
          </section>

          {/* ── upload + incoming ── */}
          <section className="grid-two">
            <div className="panel upload-panel">
              <div className="panel-title-row">
                <div>
                  <span className="panel-kicker">Input</span>
                  <h2>Upload Documents</h2>
                </div>
              </div>
              <label className="field-label" htmlFor="master-file">Master workbook (.xlsx)</label>
              <input id="master-file" className="file-input" type="file" accept=".xlsx"
                onChange={(e) => handleMasterChange(e.target.files?.[0] || null)} />
              <div className="file-name">
                {masterFile ? masterFile.name : 'No master workbook selected'}
              </div>

              <div className="row-between compact-row">
                <label className="field-label">Vendor PDFs</label>
                <button className="plain-button compact-button" type="button" onClick={addVendorRow}>+ Add File</button>
              </div>

              <div className="vendor-list">
                {vendorFiles.length ? vendorFiles.map((file, index) => (
                  <div className="vendor-row" key={`vendor-${index}`}>
                    <input className="file-input" type="file" accept=".pdf"
                      onChange={(e) => updateVendorFile(index, e.target.files?.[0] || null)} />
                    <div className="file-name">
                      {file ? file.name : `Vendor ${index + 1}: no file selected`}
                    </div>
                    <button className="plain-button danger compact-button" type="button"
                      onClick={() => removeVendorRow(index)}>Remove</button>
                  </div>
                )) : <div className="empty-line">No vendor files added yet.</div>}
              </div>

              <div className="actions action-bar">
                <button className="solid-button" type="button"
                  onClick={handleUpload} disabled={busy}>Upload Files</button>
                <button className="solid-button inverse" type="button"
                  onClick={handleRunPipeline} disabled={busy || isActive}>Run Pipeline</button>
                <button className="plain-button danger" type="button"
                  onClick={handleResetPipeline} disabled={busy}
                  title="Clear any stuck pipeline run">Reset Pipeline</button>
              </div>
            </div>

            <div className="panel">
              <div className="panel-title-row">
                <div>
                  <span className="panel-kicker">Storage</span>
                  <h2>Incoming Files</h2>
                </div>
                <span className="count-pill">{files.length}</span>
              </div>
              <div className="file-table">
                {files.length ? files.map((file) => (
                  <button
                    type="button"
                    className="file-row file-row--button"
                    key={file.file_name}
                    onClick={() => {
                      const doc = sidebarDocs.find((d) => d.id === `incoming-${file.file_name}`)
                      if (doc) setActiveDoc(doc)
                    }}
                  >
                    <strong>{file.file_name}</strong>
                    <span>{file.role}</span>
                    <span>{fmtSize(file.size_bytes)}</span>
                  </button>
                )) : <div className="empty-line">No incoming files loaded.</div>}
              </div>
            </div>
          </section>

          {/* ── summary + results ── */}
          <section className="grid-two">
            <div className="panel">
              <div className="panel-title-row">
                <div>
                  <span className="panel-kicker">Matrix</span>
                  <h2>Summary</h2>
                </div>
              </div>
              {summary ? (
                <div className="summary-grid">
                  <div><span className="muted">Total</span><strong>{summary.total_results}</strong></div>
                  {Object.entries(summary.status_counts || {}).map(([s, c]) => (
                    <div key={s}><span className="muted">{s}</span><strong>{c}</strong></div>
                  ))}
                </div>
              ) : <div className="empty-line">No summary loaded.</div>}
            </div>

            <div className="panel">
              <div className="panel-title-row">
                <div>
                  <span className="panel-kicker">Review</span>
                  <h2>Latest Results</h2>
                </div>
                <span className="count-pill">{results.length}</span>
              </div>
              <div className="result-list">
                {results.length ? results.map((row) => (
                  <div className="result-row" key={`${row.spec_id}-${row.vendor_id}`}>
                    <strong>{row.spec_id}</strong>
                    <span>{row.vendor_id}</span>
                    <span className={`verdict verdict-${normalizeVerdict(row.status)}`}>
                      {row.status}
                    </span>
                  </div>
                )) : <div className="empty-line">No result rows loaded.</div>}
              </div>
            </div>
          </section>

          {/* ── run history ── */}
          {runHistory.length > 0 && (
            <section className="panel section-block">
              <div className="panel-title-row">
                <div>
                  <span className="panel-kicker">Audit</span>
                  <h2>Run History</h2>
                </div>
              </div>
              <div className="run-history">
                <div className="run-history__head">
                  <span>Run ID</span><span>Status</span>
                  <span>Progress</span><span>Message</span><span>Updated</span>
                </div>
                {runHistory.map((r) => (
                  <div className="run-history__row" key={r.run_id}>
                    <code className="run-id-short" title={r.run_id}>{r.run_id.slice(0, 8)}…</code>
                    <StatusBadge status={r.status} />
                    <div className="run-mini-bar">
                      <div className="run-mini-fill"
                        style={{ width: `${Math.min(100, r.progress || 0)}%` }} />
                      <span>{(r.progress || 0).toFixed(0)}%</span>
                    </div>
                    <span className="run-msg" title={r.message}>
                      {(r.message || '').slice(0, 42)}{(r.message || '').length > 42 ? '…' : ''}
                    </span>
                    <span className="run-time">
                      {fmtDate(r.updated_at)}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── downloads ── */}
          <section className="panel section-block">
            <div className="row-between">
              <div>
                <span className="panel-kicker">Export</span>
                <h2>Downloads</h2>
              </div>
              <button className="solid-button compact-button" type="button"
                onClick={handleDownloadAll} disabled={busy || !outputFiles.length}>
                ⬇ Download All (ZIP)
              </button>
            </div>
            {outputFiles.length ? (
              <div className="file-table">
                {outputFiles.map((f) => {
                  const isVendor = f.file_name.startsWith('vendor_') &&
                    f.file_name !== 'vendor_comparison_matrix.xlsx'
                  const vendorId = isVendor
                    ? f.file_name.replace(/^vendor_/, '').replace(/\.xlsx$/, '') : null
                  return (
                    <div className="file-row" key={f.file_name}>
                      <strong>{f.file_name}</strong>
                      <span>{fmtSize(f.size_bytes)}</span>
                      <span className="muted inline-muted">{fmtDate(f.modified_at)}</span>
                      <div className="row-actions">
                        <button className="plain-button compact-button" type="button" disabled={busy}
                          onClick={() => isVendor
                            ? handleDownloadVendor(vendorId)
                            : handleDownloadReport()}>
                          ⬇ Download
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="empty-line">No output files yet. Run the pipeline first.</div>
            )}
          </section>

          {/* ── messages ── */}
          {(message || error) && (
            <section className="section-block status-block">
              {message && <div className="message success">{message}</div>}
              {error   && <div className="message error">{error}</div>}
            </section>
          )}

        </main>
      </div>
    </div>
  )
}
