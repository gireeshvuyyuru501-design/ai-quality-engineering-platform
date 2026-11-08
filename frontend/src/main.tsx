import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, Layers3, ShieldCheck, ExternalLink, Play, RefreshCw } from 'lucide-react'
import './style.css'

type Module = { id: string; name: string; status: 'ready' | 'missing'; provenance: string; repository: string }
type Job = {job_id?: string; id?: string; status: string; module_id:string; result?:Run; error?:string}
type Run = { id: string; module_id: string; module_name: string; run_at: string; duration_ms: number; provenance: string; live_model_evaluated: boolean; summary: Record<string, unknown>; report?: Record<string, unknown> }

let activeLocalToken = ''
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {...init, headers: {...(init?.headers || {}), ...(activeLocalToken ? {'x-local-token':activeLocalToken} : {})}})
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  }
  return response.json()
}

function App() {
  const [modules, setModules] = useState<Module[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [selected, setSelected] = useState<Run | null>(null)
  const [online, setOnline] = useState(false)
  const [analytics, setAnalytics] = useState<{total_runs:number;module_count:number;modules:{module_id:string;module_name:string;runs:number;latest:Record<string,unknown>;trend:{date:string;metric:string;value:number}[]}[]}|null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [token, setToken] = useState('')
  const [jobStatus, setJobStatus] = useState('')
  const [error, setError] = useState('')
  const refresh = async () => {
    try {
      const [health, data, history, stats] = await Promise.all([
        api<{status:string}>('/api/health'), api<Module[]>('/api/modules'), api<Run[]>('/api/runs'), api<typeof analytics>('/api/analytics')
      ])
      setOnline(health.status === 'ok'); setModules(data); setRuns(history); setAnalytics(stats); setError('')
    } catch(e) { setOnline(false); setError(String(e)) }
  }
  useEffect(() => { void refresh() }, [])
  useEffect(() => { activeLocalToken = token; }, [token])
  const exportFile = async (format: 'csv'|'json') => {
    try {
      const res = await fetch(`/api/export/${format}`, {headers:activeLocalToken ? {'x-local-token':activeLocalToken} : {}})
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href=url; a.download=`ai_quality_runs.${format}`; a.click(); URL.revokeObjectURL(url)
    } catch(e) {setError(`Export failed: ${String(e)}`)}
  }
  const run = async (id:string) => {
    setBusy(id); setError('')
    try {
      const job = await api<{job_id:string;status:string}>('/api/jobs', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({module_id:id}) })
      setJobStatus(`Queued ${id}`)
      let finished=false
      for(let attempt=0;attempt<190;attempt++) {
        await new Promise(resolve=>setTimeout(resolve,1000))
        const status = await api<Job>(`/api/jobs/${job.job_id}`)
        setJobStatus(`${id}: ${status.status}`)
        if (status.status==='completed') {if(status.result)setSelected(status.result); finished=true;break}
        if (status.status==='failed') throw new Error(status.error || 'Evaluation failed')
      }
      if (!finished) throw new Error('Polling timed out; check Jobs API')
      setJobStatus('');await refresh()
    } catch(e) { setError(`${id}: ${String(e)}`) }
    finally { setBusy(null) }
  }
  const ready = modules.filter(m => m.status === 'ready').length
  return <div className="layout"><aside><div className="brand"><ShieldCheck size={25}/> AI Quality <span>Platform</span></div><p className="asideLabel">WORKSPACE</p><div className="nav active"><Layers3 size={18}/> Overview</div><div className="nav"><Activity size={18}/> Evaluations <small>{runs.length} recorded</small></div><div className="asideFoot">v0.5 â€¢ Docker Ready</div></aside>
    <main><header><div><div className="eyebrow">ENGINEERING WORKSPACE</div><h1>Quality overview</h1><p>Execute your ten QA Python modules and review their actual reports.</p></div><div className="authControls"><label>Local access token (optional)<input type="password" autoComplete="off" value={token} onChange={e=>{activeLocalToken=e.target.value;setToken(e.target.value)}} placeholder="Only if configured on backend"/></label><button onClick={()=>void refresh()}>Connect</button><span className={'status '+(online?'online':'')}>{online?'â— API connected':'â—‹ API offline'}</span></div></header>
      <section className="stats"><article><span>Registered modules</span><strong>{modules.length}</strong><small>Local FastAPI registry</small></article><article><span>Runnable integrations</span><strong>{ready}</strong><small>Scripts detected on your PC</small></article><article><span>Recorded local runs</span><strong>{runs.length}</strong><small>Latest 30 shown â€¢ SQLite persisted</small></article></section>
      <div className="sectionHeading"><h2>Evaluation analytics</h2><div className="exportLinks"><button onClick={()=>void exportFile('csv')}>Export CSV</button><button onClick={()=>void exportFile('json')}>Export JSON</button></div></div>
      <section className="analyticsGrid">
        <article className="analyticsPanel"><h3>Recorded runs by module</h3><p>Actual local executions â€¢ not production telemetry</p>
        {analytics?.modules.length ? analytics.modules.map(m => <div className="barRow" key={m.module_id}><span title={m.module_name}>{m.module_name}</span><div className="barTrack"><div className="barFill" style={{width:`${Math.max(3,m.runs/Math.max(...analytics.modules.map(x=>x.runs))*100)}%`}}/></div><strong>{m.runs}</strong></div>) : <p>No recorded runs yet.</p>}</article>
        <article className="analyticsPanel"><h3>Latest measured metrics</h3><p>Source-specific offline baselines</p>
        {analytics?.modules.length ? analytics.modules.map(m => <div className="metricLine" key={m.module_id}><span>{m.module_name}</span><strong>{Object.entries(m.latest).filter(([k,v])=>['hit_at_k','mrr_at_k','mean_lexical_f1','support_rate','mean_quality_score','passed','total','generated_count'].includes(k) && typeof v==='number').slice(0,2).map(([k,v])=>`${k.replace(/_/g, ' ')}: ${typeof v==='number' ? Number(v.toFixed(3)):v}`).join(' Â· ') || 'Report available'}</strong></div>) : <p>Run evaluations to populate metrics.</p>}</article>
      </section>
      {jobStatus && <div className="jobStatus">Background job: {jobStatus}</div>}
      <div className="sectionHeading"><h2>Evaluation modules</h2><button className="refresh" onClick={() => void refresh()}><RefreshCw size={14}/> Refresh</button></div>
      {error && <div className="error">{error}</div>}
      <section className="cards">{modules.map((m,i) => <article className="module" key={m.id}>
        <div className="moduleTop"><span className="number">{String(i+1).padStart(2,'0')}</span><span className={'pending ' + (m.status === 'ready' ? 'ready' : '')}>{m.status === 'ready' ? 'Script found' : 'Script missing'}</span></div>
        <h3>{m.name}</h3><p>{m.provenance}</p>
        <div className="moduleActions"><button className="run" disabled={!online || m.status !== 'ready' || busy !== null} onClick={() => void run(m.id)}><Play size={14}/>{busy === m.id ? 'Runningâ€¦' : 'Run evaluation'}</button><a href={m.repository} target="_blank" rel="noreferrer">GitHub <ExternalLink size={13}/></a></div>
      </article>)}</section>
      <div className="sectionHeading"><h2>Evaluation results</h2><span>Real script outputs â€¢ local execution</span></div>
      {selected && <section className="result"><h3>{selected.module_name}</h3><p>{selected.provenance}</p><div className="metrics">{Object.entries(selected.summary).map(([key,value]) => <div className="metric" key={key}><span>{key.replace(/_/g, ' ')}</span><strong>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</strong></div>)}</div><details><summary>Inspect full JSON report</summary><pre>{JSON.stringify(selected.report ?? selected.summary, null, 2)}</pre></details></section>}
      <section className="history"><h3>Recent local runs</h3>{runs.length === 0 ? <p>Run a module above to create your first recorded evaluation.</p> : runs.map(r => <button key={r.id} onClick={() => setSelected(r)}><span>{r.module_name}</span><small>{new Date(r.run_at).toLocaleString()} â€¢ {r.duration_ms} ms</small></button>)}</section>
      <footer>Fixture and offline scores are labeled. No Gemini inference or production telemetry is claimed. A green â€œScript foundâ€ badge means the code exists, not that an evaluation has succeeded.</footer>
    </main></div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)

