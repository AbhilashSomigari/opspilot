export const dynamic = 'force-dynamic';

function pct(v:number|undefined|null){ return v == null ? '—' : `${(v*100).toFixed(1)}%`; }
function sec(v:number|undefined|null){ return v == null ? '—' : `${v.toFixed(2)} s`; }
function usd(v:number|undefined|null){ return v == null ? 'not configured' : `$${v.toFixed(4)}`; }

async function getData(){
  const base = process.env.AGENT_URL || 'http://localhost:8080';
  try {
    const r = await fetch(`${base}/evaluation/latest`, {cache:'no-store'});
    if(!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

export default async function Page(){
  const payload = await getData();
  const evalRun = payload?.evaluation;
  const s = evalRun?.summary;
  const baseline = payload?.baseline;
  const rows = evalRun?.results || [];
  return <main>
    <h1>OpsPilot</h1>
    <p>Production incident-response agent evaluation dashboard</p>
    {!s ? <div className="card"><b>No evaluation run yet.</b><p>Run <code>python eval/baseline.py</code> and <code>python eval/runner.py</code>.</p></div> : <>
      <div className="grid">
        <div className="card"><div className="label">Root-cause Top-1</div><div className="value">{pct(s.root_cause_top1_accuracy)}</div></div>
        <div className="card"><div className="label">Resolution success</div><div className="value">{pct(s.incident_resolution_success_rate)}</div></div>
        <div className="card"><div className="label">Tool correctness</div><div className="value">{pct(s.tool_call_correctness)}</div></div>
        <div className="card"><div className="label">Unsafe action rate</div><div className="value">{pct(s.unsafe_action_rate)}</div></div>
        <div className="card"><div className="label">Unsupported claims</div><div className="value">{pct(s.unsupported_claim_rate)}</div></div>
        <div className="card"><div className="label">Average investigation</div><div className="value">{sec(s.average_investigation_time_s)}</div></div>
        <div className="card"><div className="label">p95 latency</div><div className="value">{sec(s.p95_latency_s)}</div></div>
        <div className="card"><div className="label">Cost / incident</div><div className="value" style={{fontSize:22}}>{usd(s.cost_per_incident_usd)}</div></div>
      </div>

      <section className="section card">
        <div className="label">Agent vs single-prompt baseline</div>
        <div className="row"><span>OpsPilot</span><div className="bar"><div className="fill" style={{width:pct(s.root_cause_top1_accuracy)}}/></div><b>{pct(s.root_cause_top1_accuracy)}</b></div>
        <div className="row"><span>Single prompt</span><div className="bar"><div className="fill" style={{width:pct(baseline?.root_cause_top1_accuracy)}}/></div><b>{pct(baseline?.root_cause_top1_accuracy)}</b></div>
      </section>

      <section className="section card">
        <div className="label">Accuracy by failure category</div>
        {Object.entries(s.categories || {}).map(([name,v]:any)=><div className="row" key={name}><span>{name}</span><div className="bar"><div className="fill" style={{width:pct(v.top1_accuracy)}}/></div><b>{pct(v.top1_accuracy)}</b></div>)}
      </section>

      <section className="section card" style={{overflowX:'auto'}}>
        <div className="label" style={{marginBottom:10}}>Incident cases</div>
        <table><thead><tr><th>Case</th><th>Injected service</th><th>Category</th><th>Top-1</th><th>Latency</th><th>Root cause</th></tr></thead>
        <tbody>{rows.map((r:any)=><tr key={r.case_id}><td>{r.case_id}</td><td>{r.injected_service}</td><td>{r.category}</td><td className={r.top1_correct?'good':'bad'}>{r.top1_correct?'PASS':'FAIL'}</td><td>{sec(r.investigation_latency_s)}</td><td>{r.root_cause || r.error}</td></tr>)}</tbody></table>
      </section>
    </>}
  </main>;
}
