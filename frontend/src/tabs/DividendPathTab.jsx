import { useState, useEffect, useCallback, useRef } from 'react'

const API = '/api/dividend-path'

const C = {
  bg:     '#0f1117', card:   '#1a1f2e', bdr:    '#2d3748',
  accent: '#48bb78', blue:   '#63b3ed', gold:   '#ecc94b',
  muted:  '#718096', text:   '#e2e8f0', sub:    '#a0aec0',
  red:    '#fc8181', reit:   '#9f7aea', arist:  '#f6ad55',
  etf:    '#63b3ed', custom: '#ed8936',
}
const CAT_COLOR = { etf: C.etf, aristocrat: C.arist, reit: C.reit, custom: C.custom }
const CAT_LABEL = { etf: 'ETF', aristocrat: 'Dividend Aristocrat', reit: 'REIT / BDC', custom: 'Custom' }

const fmt$  = v => `$${Number(v||0).toLocaleString('en-US',{maximumFractionDigits:0})}`
const fmt$d = v => `$${Number(v||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`
const fmtP  = v => `${Number(v||0).toFixed(2)}%`

// ─── Sparkline ───────────────────────────────────────────────────────────────
function IncomeSparkline({ data }) {
  if (!data?.length) return null
  const W=500, H=100, PAD=8, GOAL=1000
  const months=data.map(d=>d.month), incomes=data.map(d=>d.monthly_income)
  const maxInc=Math.max(...incomes,GOAL*1.1)
  const minMo=months[0], maxMo=months[months.length-1]
  const x=m=>PAD+((m-minMo)/Math.max(maxMo-minMo,1))*(W-PAD*2)
  const y=v=>H-PAD-(v/maxInc)*(H-PAD*2)
  const pathD=data.map((d,i)=>`${i===0?'M':'L'}${x(d.month).toFixed(1)},${y(d.monthly_income).toFixed(1)}`).join(' ')
  const areaD=`${pathD} L${x(maxMo)},${H-PAD} L${x(minMo)},${H-PAD} Z`
  const goalY=y(GOAL)
  const goalPt=data.find(d=>d.monthly_income>=GOAL)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%',height:'90px'}}>
      <defs>
        <linearGradient id="ig" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.accent} stopOpacity=".4"/>
          <stop offset="100%" stopColor={C.accent} stopOpacity="0"/>
        </linearGradient>
      </defs>
      <line x1={PAD} y1={goalY} x2={W-PAD} y2={goalY} stroke={C.gold} strokeWidth="1" strokeDasharray="4 3"/>
      <text x={W-PAD-2} y={goalY-3} fontSize="9" fill={C.gold} textAnchor="end">$1K/mo goal</text>
      <path d={areaD} fill="url(#ig)"/>
      <path d={pathD} fill="none" stroke={C.accent} strokeWidth="2" strokeLinejoin="round"/>
      {goalPt&&<circle cx={x(goalPt.month)} cy={y(goalPt.monthly_income)} r="4" fill={C.gold} stroke="#fff" strokeWidth="1.5"/>}
    </svg>
  )
}

// ─── Allocation bar ──────────────────────────────────────────────────────────
function AllocBar({ portfolio, totalCapital }) {
  if (!portfolio?.length) return null
  const total = totalCapital || portfolio.reduce((s,h)=>s+(h.dollar_amount||0),0) || 1
  return (
    <div style={{display:'flex',height:'10px',borderRadius:'6px',overflow:'hidden',gap:'2px'}}>
      {portfolio.map(h=>{
        const w = h.dollar_amount!=null ? (h.dollar_amount/total*100) : (h.allocation_pct||0)
        return <div key={h.ticker} title={`${h.ticker} ${fmt$(h.dollar_amount??0)}`}
          style={{flex:Math.max(w,0.5),background:CAT_COLOR[h.category]||C.muted,minWidth:'2px'}}/>
      })}
    </div>
  )
}

// ─── Stat box ────────────────────────────────────────────────────────────────
function StatBox({label,value,color}) {
  return (
    <div style={{background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'8px',padding:'12px 16px'}}>
      <div style={{fontSize:'11px',color:C.muted}}>{label}</div>
      <div style={{fontSize:'20px',fontWeight:700,color:color||C.text}}>{value}</div>
    </div>
  )
}

function Metric({label,value,color}) {
  return (
    <div>
      <div style={{fontSize:'11px',color:C.muted}}>{label}</div>
      <div style={{fontSize:'13px',fontWeight:600,color:color||C.text}}>{value??'—'}</div>
    </div>
  )
}

// ─── Read-only holding card ───────────────────────────────────────────────────
function HoldingCard({h, capital}) {
  const cc = CAT_COLOR[h.category]||C.muted
  const invested = h.dollar_amount ?? (capital*(h.allocation_pct||0)/100)
  const shares   = invested&&h.price>0 ? (invested/h.price).toFixed(2) : '—'
  const moIncome = invested&&h.annual_yield_pct>0 ? invested*h.annual_yield_pct/100/12 : 0
  return (
    <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',padding:'16px',display:'flex',flexDirection:'column',gap:'10px'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
        <div>
          <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
            <span style={{fontSize:'18px',fontWeight:700,color:C.text}}>{h.ticker}</span>
            <span style={{fontSize:'11px',fontWeight:600,color:cc,background:`${cc}22`,border:`1px solid ${cc}44`,borderRadius:'4px',padding:'1px 6px'}}>
              {CAT_LABEL[h.category]||h.category}
            </span>
          </div>
          <div style={{fontSize:'12px',color:C.muted,marginTop:'2px'}}>{h.name}</div>
        </div>
        <div style={{textAlign:'right'}}>
          <div style={{fontSize:'20px',fontWeight:700,color:cc}}>{fmt$(invested)}</div>
          <div style={{fontSize:'11px',color:C.muted}}>initial</div>
        </div>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px 12px'}}>
        <Metric label="Price"          value={fmt$d(h.price)}/>
        <Metric label="Annual Yield"   value={fmtP(h.annual_yield_pct)} color={C.accent}/>
        <Metric label="Div Growth (1Y)" value={`${h.div_growth_pct>0?'+':''}${(h.div_growth_pct||0).toFixed(1)}%`} color={h.div_growth_pct>=0?C.accent:C.red}/>
        <Metric label="Div Payments"   value={`${h.streak_payments||0} tracked`}/>
        {h.error&&<div style={{gridColumn:'span 2',fontSize:'11px',color:C.red}}>⚠ {h.error}</div>}
      </div>
      <div style={{borderTop:`1px solid ${C.bdr}`,paddingTop:'8px',display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'6px'}}>
        <Metric label="Initial"    value={fmt$(invested)} color={cc}/>
        <Metric label="Shares"     value={shares}/>
        <Metric label="Mo. Income" value={fmt$d(moIncome)} color={C.accent}/>
      </div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',borderTop:`1px solid ${C.bdr}`,paddingTop:'8px'}}>
        <div style={{fontSize:'12px',color:C.muted}}>
          DCA: <span style={{color:C.blue,fontWeight:600}}>{(h.dca_pct||0).toFixed(1)}%</span> of weekly buy
        </div>
        {h.score!=null&&<span style={{fontSize:'12px',color:C.sub}}>Score <strong style={{color:C.text}}>{h.score}</strong>/100</span>}
      </div>
    </div>
  )
}

// ─── Editable card ───────────────────────────────────────────────────────────
function EditableCard({h, idx, onChange, onRemove, startingCapital, weeklyDca, dcaTotal}) {
  const cc = CAT_COLOR[h.category]||C.custom
  const moIncome = h.dollar_amount&&h.annual_yield_pct>0 ? h.dollar_amount*h.annual_yield_pct/100/12 : null
  const dcaWeekly = h.dca_pct ? (weeklyDca*h.dca_pct/100).toFixed(2) : '—'
  const amtPct = startingCapital>0 ? (h.dollar_amount/startingCapital*100).toFixed(1) : '—'
  const dcaErr = Math.abs(dcaTotal-100)>0.5
  return (
    <div style={{background:C.card,border:`2px solid ${h._dirty?C.gold:C.bdr}`,borderRadius:'12px',padding:'16px',display:'flex',flexDirection:'column',gap:'12px'}}>
      {/* Ticker + name */}
      <div style={{display:'flex',alignItems:'flex-start',gap:'8px'}}>
        <div style={{flex:'0 0 120px'}}>
          <label style={{fontSize:'11px',color:C.muted,display:'block',marginBottom:'3px'}}>Ticker</label>
          <input value={h.ticker} onChange={e=>onChange(idx,'ticker',e.target.value.toUpperCase())}
            style={{width:'100%',background:'#0f1117',border:`1px solid ${h._dirty?C.gold:C.bdr}`,borderRadius:'6px',
              padding:'7px 10px',color:C.text,fontSize:'16px',fontWeight:700}}/>
        </div>
        <div style={{flex:1,paddingTop:'18px',fontSize:'12px',color:h._dirty?C.gold:C.muted,lineHeight:1.3}}>
          {h._dirty ? '⚡ Changed — click Run Analysis' : h.name}
        </div>
        <button onClick={()=>onRemove(idx)} title="Remove"
          style={{marginTop:'18px',background:'transparent',border:`1px solid ${C.red}55`,color:C.red,
            borderRadius:'6px',padding:'4px 8px',cursor:'pointer',fontSize:'12px'}}>✕</button>
      </div>
      {/* Amount + DCA */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px'}}>
        <div>
          <label style={{fontSize:'11px',color:C.muted,display:'block',marginBottom:'3px'}}>
            Initial ($) <span style={{color:C.sub,fontWeight:400}}>= {amtPct}%</span>
          </label>
          <input type="number" value={h.dollar_amount}
            onChange={e=>onChange(idx,'dollar_amount',Number(e.target.value))}
            style={{width:'100%',background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'6px',padding:'7px 10px',color:C.text,fontSize:'14px'}}/>
        </div>
        <div>
          <label style={{fontSize:'11px',color:dcaErr?C.red:C.muted,display:'block',marginBottom:'3px'}}>
            DCA % <span style={{color:C.sub,fontWeight:400}}>≈ ${dcaWeekly}/wk</span>
          </label>
          <input type="number" step="0.1" min="0" max="100" value={h.dca_pct}
            onChange={e=>onChange(idx,'dca_pct',Number(e.target.value))}
            style={{width:'100%',background:'#0f1117',border:`1px solid ${dcaErr?C.red:C.bdr}`,borderRadius:'6px',padding:'7px 10px',color:C.text,fontSize:'14px'}}/>
        </div>
      </div>
      {/* Live metrics (only after data is fetched) */}
      {!h._dirty&&h.price>0&&(
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 1fr',gap:'6px',opacity:.85}}>
          <Metric label="Price"      value={fmt$d(h.price)}/>
          <Metric label="Yield"      value={fmtP(h.annual_yield_pct)} color={C.accent}/>
          <Metric label="Mo. Income" value={moIncome!=null?fmt$d(moIncome):'—'} color={C.accent}/>
        </div>
      )}
      {h.error&&<div style={{fontSize:'11px',color:C.red}}>⚠ {h.error}</div>}
    </div>
  )
}

// ─── Projection table ─────────────────────────────────────────────────────────
function ProjectionTable({snapshots}) {
  if (!snapshots?.length) return null
  return (
    <div style={{overflowX:'auto'}}>
      <table style={{width:'100%',borderCollapse:'collapse',fontSize:'13px'}}>
        <thead>
          <tr style={{borderBottom:`1px solid ${C.bdr}`}}>
            {['Period','Portfolio Value','Monthly Income','Annual Income','Total Invested','Gain','Yield on Cost'].map(h=>(
              <th key={h} style={{padding:'8px 12px',textAlign:h==='Period'?'left':'right',color:C.muted,fontWeight:600,whiteSpace:'nowrap'}}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {snapshots.map((row,i)=>{
            const hit=row.monthly_income>=1000
            return (
              <tr key={i} style={{borderBottom:`1px solid ${C.bdr}22`,background:hit?`${C.gold}10`:'transparent'}}>
                <td style={{padding:'7px 12px',color:C.text,whiteSpace:'nowrap'}}>{hit&&'🎯 '}Yr {row.year} Mo {row.month_of_year}</td>
                <td style={{padding:'7px 12px',textAlign:'right',color:C.blue}}>{fmt$(row.portfolio_value)}</td>
                <td style={{padding:'7px 12px',textAlign:'right',color:hit?C.gold:C.accent,fontWeight:hit?700:400}}>{fmt$d(row.monthly_income)}</td>
                <td style={{padding:'7px 12px',textAlign:'right',color:C.accent}}>{fmt$(row.annual_income)}</td>
                <td style={{padding:'7px 12px',textAlign:'right',color:C.muted}}>{fmt$(row.total_contributed)}</td>
                <td style={{padding:'7px 12px',textAlign:'right',color:row.growth>=0?C.accent:C.red}}>{row.growth>=0?'+':''}{fmt$(row.growth)}</td>
                <td style={{padding:'7px 12px',textAlign:'right',color:C.sub}}>{row.yield_on_cost?.toFixed(2)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── Lump sum ────────────────────────────────────────────────────────────────
function LumpSumPanel({portfolio, startingCapital, weeklyDca}) {
  const [amount, setAmount]   = useState('')
  const [result, setResult]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const submit = async e => {
    e.preventDefault()
    const val=parseFloat(amount.replace(/,/g,''))
    if (!val||val<=0) return
    setLoading(true); setError(null)
    try {
      const r=await fetch(`${API}/lump-sum`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({lump_amount:val,starting_capital:startingCapital,weekly_dca:weeklyDca})})
      if (!r.ok) throw new Error((await r.json()).detail||'Error')
      setResult(await r.json())
    } catch(err){setError(err.message)} finally{setLoading(false)}
  }

  return (
    <div style={{background:C.card,border:`1px solid ${C.gold}55`,borderRadius:'12px',padding:'20px'}}>
      <div style={{fontSize:'16px',fontWeight:700,color:C.gold,marginBottom:'4px'}}>💰 Lump Sum Allocator</div>
      <div style={{fontSize:'13px',color:C.muted,marginBottom:'16px'}}>Got a bonus? Enter the amount and we'll show you exactly how to deploy it.</div>
      <form onSubmit={submit} style={{display:'flex',gap:'10px',alignItems:'flex-end',flexWrap:'wrap'}}>
        <div>
          <label style={{fontSize:'12px',color:C.muted,display:'block',marginBottom:'4px'}}>Amount ($)</label>
          <input type="text" value={amount} onChange={e=>setAmount(e.target.value)} placeholder="e.g. 5000"
            style={{background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'6px',padding:'8px 12px',color:C.text,fontSize:'14px',width:'160px'}}/>
        </div>
        <button type="submit" disabled={loading||!amount}
          style={{padding:'8px 20px',background:loading?C.muted:C.gold,color:'#000',border:'none',
            borderRadius:'6px',fontWeight:700,cursor:loading?'not-allowed':'pointer',fontSize:'14px'}}>
          {loading?'Calculating…':'Allocate'}
        </button>
      </form>
      {error&&<div style={{color:C.red,marginTop:'10px',fontSize:'13px'}}>{error}</div>}
      {result&&(
        <div style={{marginTop:'20px'}}>
          <div style={{display:'flex',gap:'16px',marginBottom:'16px',flexWrap:'wrap'}}>
            <StatBox label="Deployed"           value={fmt$(result.lump_amount)} color={C.gold}/>
            <StatBox label="Added Mo. Income"   value={fmt$d(result.total_added_monthly_income)} color={C.accent}/>
            <StatBox label="Added Annual Income" value={fmt$(result.total_added_annual_income)} color={C.accent}/>
          </div>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(240px,1fr))',gap:'10px'}}>
            {result.allocation.map(a=>(
              <div key={a.ticker} style={{background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'8px',padding:'12px',display:'flex',flexDirection:'column',gap:'6px'}}>
                <div style={{display:'flex',justifyContent:'space-between'}}>
                  <span style={{fontWeight:700,color:C.text}}>{a.ticker}</span>
                  <span style={{fontSize:'11px',color:CAT_COLOR[a.category]||C.muted,background:`${CAT_COLOR[a.category]||C.muted}22`,padding:'1px 6px',borderRadius:'4px'}}>{a.allocation_pct}%</span>
                </div>
                <div style={{fontSize:'12px',color:C.muted}}>{a.name}</div>
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'4px',marginTop:'4px'}}>
                  <Metric label="Deploy"         value={fmt$(a.lump_amount)} color={C.gold}/>
                  <Metric label="Shares"         value={a.shares_to_buy?.toFixed(3)}/>
                  <Metric label="Yield"          value={fmtP(a.annual_yield_pct)} color={C.accent}/>
                  <Metric label="Added Mo. Inc." value={fmt$d(a.added_monthly_income)} color={C.accent}/>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Results section (shared by recommendation + custom) ─────────────────────
function ResultsView({activeData, startingCapital, weeklyDca, showProj, setShowProj, showAll, setShowAll, isCustom}) {
  const port = activeData.portfolio
  const goal = activeData.reached_goal_at
  const monthlyContrib = Math.round(weeklyDca*52/12)

  return (
    <>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(165px,1fr))',gap:'12px'}}>
        <StatBox label="Starting Capital"   value={fmt$(startingCapital)} color={C.blue}/>
        <StatBox label="Monthly DCA"        value={fmt$(monthlyContrib)} color={C.blue}/>
        <StatBox label="Blended Yield"      value={fmtP(activeData.blended_yield_pct)} color={C.accent}/>
        <StatBox label="Starting Mo. Inc."  value={fmt$d(activeData.starting_monthly_income)} color={C.accent}/>
        {goal
          ? <StatBox label="🎯 Goal Reached" value={`Yr ${goal.year}, Mo ${goal.month}`} color={C.gold}/>
          : <StatBox label="Goal Status"     value="30Y+ horizon" color={C.muted}/>}
      </div>

      <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',padding:'16px 20px'}}>
        <div style={{fontSize:'14px',fontWeight:600,color:C.text,marginBottom:'12px'}}>
          {isCustom ? 'Your Custom Allocation' : 'Portfolio Allocation'}
        </div>
        <AllocBar portfolio={port} totalCapital={startingCapital}/>
        <div style={{display:'flex',gap:'14px',marginTop:'10px',flexWrap:'wrap'}}>
          {port?.map(h=>(
            <div key={h.ticker} style={{display:'flex',alignItems:'center',gap:'5px'}}>
              <span style={{width:'10px',height:'10px',borderRadius:'2px',background:CAT_COLOR[h.category]||C.muted,display:'inline-block'}}/>
              <span style={{fontSize:'12px',color:C.sub}}>{h.ticker} {fmt$(h.dollar_amount??(startingCapital*(h.allocation_pct||0)/100))}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',padding:'16px 20px'}}>
        <div style={{fontSize:'14px',fontWeight:600,color:C.text,marginBottom:'4px'}}>Income Growth Trajectory</div>
        <div style={{fontSize:'12px',color:C.muted,marginBottom:'10px'}}>
          Monthly dividend income (DRIP + {fmt$(weeklyDca)}/week DCA){isCustom&&<span style={{color:C.gold}}> — Custom portfolio</span>}
        </div>
        <IncomeSparkline data={activeData.projection}/>
      </div>

      <div>
        <div style={{fontSize:'16px',fontWeight:700,color:C.text,marginBottom:'12px'}}>
          {isCustom ? '📋 Your Portfolio' : '📋 Recommended Portfolio — 6 Holdings'}
        </div>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(290px,1fr))',gap:'14px'}}>
          {port?.map(h=><HoldingCard key={h.ticker} h={h} capital={startingCapital}/>)}
        </div>
      </div>

      <LumpSumPanel portfolio={port} startingCapital={startingCapital} weeklyDca={weeklyDca}/>

      <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',overflow:'hidden'}}>
        <div style={{padding:'16px 20px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
          <div>
            <div style={{fontSize:'14px',fontWeight:600,color:C.text}}>DRIP + DCA Projection</div>
            <div style={{fontSize:'12px',color:C.muted,marginTop:'2px'}}>
              Every 6-month snapshot — {fmtP(activeData.blended_yield_pct)} blended yield, 5% annual appreciation, DRIP reinvestment
            </div>
          </div>
          <button onClick={()=>setShowProj(s=>!s)}
            style={{padding:'6px 14px',background:'transparent',border:`1px solid ${C.bdr}`,borderRadius:'6px',color:C.sub,cursor:'pointer',fontSize:'13px'}}>
            {showProj?'Hide':'Show'}
          </button>
        </div>
        {showProj&&<div style={{borderTop:`1px solid ${C.bdr}`}}><ProjectionTable snapshots={activeData.projection}/></div>}
      </div>
    </>
  )
}

// ─── Main tab ─────────────────────────────────────────────────────────────────
export default function DividendPathTab() {
  const [data,         setData]         = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState(null)
  const [showAll,      setShowAll]      = useState(false)
  const [showProj,     setShowProj]     = useState(false)
  const [startCap,     setStartCap]     = useState(61000)
  const [weeklyDca,    setWeeklyDca]    = useState(500)

  // Edit / custom portfolio
  const [editMode,     setEditMode]     = useState(false)
  const [customH,      setCustomH]      = useState(null)
  const [customResult, setCustomResult] = useState(null)
  const [customLoading,setCustomLoading]= useState(false)
  const [customError,  setCustomError]  = useState(null)
  const [addTicker,    setAddTicker]    = useState('')

  const load = useCallback(async (force=false)=>{
    setLoading(true); setError(null)
    try {
      const r=await fetch(`${API}/recommend?starting_capital=${startCap}&weekly_dca=${weeklyDca}${force?'&force=true':''}`)
      if (!r.ok) throw new Error((await r.json()).detail||`HTTP ${r.status}`)
      const d=await r.json()
      setData(d); setCustomResult(null); setEditMode(false); setCustomH(null)
    } catch(err){setError(err.message)} finally{setLoading(false)}
  },[startCap,weeklyDca])

  useEffect(()=>{load()},[load])

  const enterEdit = () => {
    const base=(data?.portfolio||[]).map(h=>({
      ...h,
      dollar_amount: h.dollar_amount ?? Math.round(startCap*(h.allocation_pct||0)/100),
      dca_pct: h.dca_pct ?? (h.allocation_pct||0),
      _dirty: false,
    }))
    setCustomH(base); setCustomResult(null); setEditMode(true)
  }

  const exitEdit = () => { setEditMode(false); setCustomH(null); setCustomResult(null) }

  const updateHolding = (idx,field,val) => {
    setCustomH(prev=>prev.map((h,i)=>{
      if (i!==idx) return h
      const u={...h,[field]:val}
      if (field==='ticker') u._dirty=true
      return u
    }))
  }

  const removeHolding = idx => setCustomH(prev=>prev.filter((_,i)=>i!==idx))

  const addHolding = () => {
    const t=addTicker.trim().toUpperCase()
    if (!t) return
    const n=customH.length+1
    setCustomH(prev=>[...prev,{
      ticker:t,name:t,category:'custom',
      dollar_amount:Math.round(startCap/n),
      dca_pct:parseFloat((100/n).toFixed(1)),
      price:0,annual_yield_pct:0,annual_div:0,div_growth_pct:0,
      streak_payments:0,high_52w:0,low_52w:0,drawdown_from_high_pct:0,score:0,_dirty:true,
    }])
    setAddTicker('')
  }

  const dcaTotal = customH ? customH.reduce((s,h)=>s+(Number(h.dca_pct)||0),0) : 100
  const amtTotal = customH ? customH.reduce((s,h)=>s+(Number(h.dollar_amount)||0),0) : startCap
  const amtDiff  = amtTotal - startCap

  const runCustom = async () => {
    if (Math.abs(dcaTotal-100)>0.5) return
    setCustomLoading(true); setCustomError(null)
    try {
      const r=await fetch(`${API}/run-custom`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          holdings:customH.map(h=>({ticker:h.ticker,dollar_amount:Number(h.dollar_amount),dca_pct:Number(h.dca_pct)})),
          starting_capital:startCap,weekly_dca:weeklyDca,
        }),
      })
      if (!r.ok) throw new Error((await r.json()).detail||'Error')
      const result=await r.json()
      setCustomH(result.portfolio.map(h=>({...h,_dirty:false})))
      setCustomResult(result)
    } catch(err){setCustomError(err.message)} finally{setCustomLoading(false)}
  }

  const activeData = customResult || data

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'24px'}}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div style={{background:'linear-gradient(135deg,#1a2744 0%,#1a1f2e 100%)',
        border:`1px solid ${C.blue}33`,borderRadius:'12px',padding:'20px 24px'}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',flexWrap:'wrap',gap:'16px'}}>
          <div>
            <div style={{fontSize:'22px',fontWeight:700,color:C.text}}>📈 Dividend Income Path</div>
            <div style={{fontSize:'13px',color:C.muted,marginTop:'4px'}}>
              Safety-first portfolio to reach <strong style={{color:C.gold}}>$1,000/month</strong> passive income via DRIP + DCA.
              {customResult&&<span style={{color:C.gold,marginLeft:'8px'}}>● Custom portfolio active</span>}
            </div>
          </div>
          <div style={{display:'flex',gap:'8px',flexWrap:'wrap'}}>
            {editMode ? (
              <button onClick={exitEdit}
                style={{padding:'8px 14px',background:'transparent',border:`1px solid ${C.bdr}`,color:C.sub,borderRadius:'8px',cursor:'pointer',fontSize:'13px'}}>
                ← Back to Recommendation
              </button>
            ) : (
              <>
                <button onClick={enterEdit} disabled={!data}
                  style={{padding:'8px 14px',background:C.gold,color:'#000',border:'none',borderRadius:'8px',fontWeight:700,cursor:data?'pointer':'not-allowed',fontSize:'13px'}}>
                  ✏️ Customize Portfolio
                </button>
                <button onClick={()=>load(true)} disabled={loading}
                  style={{padding:'8px 14px',background:C.blue,color:'#000',border:'none',borderRadius:'8px',fontWeight:700,cursor:loading?'not-allowed':'pointer',fontSize:'13px',opacity:loading?.6:1}}>
                  {loading?'⟳ Scanning…':'⟳ Refresh'}
                </button>
              </>
            )}
          </div>
        </div>

        <div style={{display:'flex',gap:'16px',marginTop:'16px',flexWrap:'wrap',alignItems:'flex-end'}}>
          <div>
            <label style={{fontSize:'11px',color:C.muted,display:'block',marginBottom:'4px'}}>Starting Capital ($)</label>
            <input type="number" value={startCap} onChange={e=>setStartCap(Number(e.target.value))}
              style={{background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'6px',padding:'7px 10px',color:C.text,fontSize:'14px',width:'130px'}}/>
          </div>
          <div>
            <label style={{fontSize:'11px',color:C.muted,display:'block',marginBottom:'4px'}}>Weekly DCA ($)</label>
            <input type="number" value={weeklyDca} onChange={e=>setWeeklyDca(Number(e.target.value))}
              style={{background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'6px',padding:'7px 10px',color:C.text,fontSize:'14px',width:'110px'}}/>
          </div>
          {!editMode&&(
            <button onClick={()=>load(false)} disabled={loading}
              style={{padding:'7px 16px',background:C.accent,color:'#000',border:'none',borderRadius:'6px',fontWeight:700,cursor:loading?'not-allowed':'pointer',fontSize:'13px'}}>
              Apply
            </button>
          )}
          <div style={{fontSize:'12px',color:C.muted,alignSelf:'center'}}>
            ≈ {fmt$(Math.round(weeklyDca*52/12))}/month contributed
          </div>
        </div>
      </div>

      {error&&<div style={{background:'#2d1515',border:`1px solid ${C.red}`,borderRadius:'10px',padding:'16px',color:C.red}}>{error}</div>}

      {loading&&!data&&(
        <div style={{textAlign:'center',padding:'60px',color:C.muted}}>
          <div style={{fontSize:'32px',marginBottom:'12px'}}>📊</div>
          <div>Analyzing dividend universe and building your income path…</div>
          <div style={{fontSize:'12px',marginTop:'6px'}}>First load may take 30-60 seconds.</div>
        </div>
      )}

      {/* ── EDIT MODE ───────────────────────────────────────────────────── */}
      {editMode&&customH&&(
        <>
          {/* Edit toolbar */}
          <div style={{background:C.card,border:`2px solid ${C.gold}55`,borderRadius:'12px',padding:'16px 20px'}}>
            <div style={{fontSize:'15px',fontWeight:700,color:C.gold,marginBottom:'12px'}}>✏️ Customize Your Portfolio</div>

            <div style={{display:'flex',gap:'24px',flexWrap:'wrap',marginBottom:'12px',fontSize:'13px'}}>
              <span>
                <span style={{color:C.muted}}>Total initial: </span>
                <strong style={{color:Math.abs(amtDiff)>500?C.red:C.accent}}>{fmt$(amtTotal)}</strong>
                {Math.abs(amtDiff)>500&&<span style={{color:C.red,marginLeft:'6px'}}>({amtDiff>0?'+':''}{fmt$(amtDiff)} vs {fmt$(startCap)})</span>}
              </span>
              <span>
                <span style={{color:C.muted}}>DCA total: </span>
                <strong style={{color:Math.abs(dcaTotal-100)>0.5?C.red:C.accent}}>{dcaTotal.toFixed(1)}%</strong>
                {Math.abs(dcaTotal-100)>0.5&&<span style={{color:C.red,marginLeft:'6px'}}>(must = 100%)</span>}
              </span>
            </div>

            <div style={{display:'flex',gap:'8px',alignItems:'center',marginBottom:'14px',flexWrap:'wrap'}}>
              <input value={addTicker} onChange={e=>setAddTicker(e.target.value.toUpperCase())}
                placeholder="Add ticker (e.g. GS)" onKeyDown={e=>e.key==='Enter'&&addHolding()}
                style={{background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'6px',padding:'7px 12px',
                  color:C.text,fontSize:'15px',fontWeight:700,width:'170px'}}/>
              <button onClick={addHolding} disabled={!addTicker.trim()}
                style={{padding:'7px 14px',background:C.accent,color:'#000',border:'none',borderRadius:'6px',
                  fontWeight:700,cursor:addTicker.trim()?'pointer':'not-allowed',fontSize:'13px'}}>+ Add</button>
              <span style={{fontSize:'12px',color:C.muted}}>Swap or add any ticker — type it in an existing card or add a new one</span>
            </div>

            <div style={{display:'flex',gap:'10px',alignItems:'center',flexWrap:'wrap'}}>
              <button onClick={runCustom} disabled={customLoading||Math.abs(dcaTotal-100)>0.5}
                style={{padding:'10px 24px',background:customLoading?C.muted:C.gold,color:'#000',border:'none',
                  borderRadius:'8px',fontWeight:700,fontSize:'14px',
                  cursor:(customLoading||Math.abs(dcaTotal-100)>0.5)?'not-allowed':'pointer'}}>
                {customLoading?'⟳ Fetching data & running analysis…':'▶ Run My Analysis'}
              </button>
              {customLoading&&<span style={{fontSize:'12px',color:C.muted}}>Fetching live data for each ticker…</span>}
            </div>
            {customError&&<div style={{color:C.red,marginTop:'10px',fontSize:'13px'}}>{customError}</div>}
          </div>

          {/* Editable cards */}
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(310px,1fr))',gap:'14px'}}>
            {customH.map((h,idx)=>(
              <EditableCard key={idx} h={h} idx={idx} onChange={updateHolding} onRemove={removeHolding}
                startingCapital={startCap} weeklyDca={weeklyDca} dcaTotal={dcaTotal}/>
            ))}
          </div>

          {/* Custom results */}
          {customResult&&(
            <>
              <div style={{background:C.card,border:`1px solid ${C.gold}55`,borderRadius:'12px',padding:'16px 20px'}}>
                <div style={{fontSize:'14px',fontWeight:600,color:C.gold,marginBottom:'12px'}}>📊 Custom Portfolio Results</div>
                <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(155px,1fr))',gap:'10px'}}>
                  <StatBox label="Blended Yield"      value={fmtP(customResult.blended_yield_pct)} color={C.accent}/>
                  <StatBox label="Starting Mo. Inc."  value={fmt$d(customResult.starting_monthly_income)} color={C.accent}/>
                  {customResult.reached_goal_at
                    ? <StatBox label="🎯 Goal Reached" value={`Yr ${customResult.reached_goal_at.year}, Mo ${customResult.reached_goal_at.month}`} color={C.gold}/>
                    : <StatBox label="Goal"            value="30Y+ horizon" color={C.muted}/>}
                </div>
              </div>
              <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',padding:'16px 20px'}}>
                <div style={{fontSize:'14px',fontWeight:600,color:C.text,marginBottom:'8px'}}>Income Trajectory (Your Portfolio)</div>
                <IncomeSparkline data={customResult.projection}/>
              </div>
              <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',overflow:'hidden'}}>
                <div style={{padding:'14px 20px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                  <div style={{fontSize:'14px',fontWeight:600,color:C.text}}>DRIP + DCA Projection (Custom)</div>
                  <button onClick={()=>setShowProj(s=>!s)}
                    style={{padding:'5px 12px',background:'transparent',border:`1px solid ${C.bdr}`,borderRadius:'6px',color:C.sub,cursor:'pointer',fontSize:'13px'}}>
                    {showProj?'Hide':'Show'}
                  </button>
                </div>
                {showProj&&<div style={{borderTop:`1px solid ${C.bdr}`}}><ProjectionTable snapshots={customResult.projection}/></div>}
              </div>
            </>
          )}
        </>
      )}

      {/* ── RECOMMENDATION / CUSTOM RESULTS ─────────────────────────────── */}
      {!editMode&&activeData&&(
        <>
          <ResultsView
            activeData={activeData}
            startingCapital={startCap}
            weeklyDca={weeklyDca}
            showProj={showProj}
            setShowProj={setShowProj}
            showAll={showAll}
            setShowAll={setShowAll}
            isCustom={!!customResult}
          />

          {/* Top candidates — only show on recommendation view */}
          {!customResult&&data?.top_candidates?.length>0&&(
            <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',overflow:'hidden'}}>
              <div style={{padding:'16px 20px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <div style={{fontSize:'14px',fontWeight:600,color:C.text}}>
                  Full Ranked Candidates ({data.scored_count} scored)
                </div>
                <button onClick={()=>setShowAll(s=>!s)}
                  style={{padding:'6px 14px',background:'transparent',border:`1px solid ${C.bdr}`,borderRadius:'6px',color:C.sub,cursor:'pointer',fontSize:'13px'}}>
                  {showAll?'Collapse':'View All'}
                </button>
              </div>
              {showAll&&(
                <div style={{borderTop:`1px solid ${C.bdr}`,overflowX:'auto'}}>
                  <table style={{width:'100%',borderCollapse:'collapse',fontSize:'13px'}}>
                    <thead>
                      <tr style={{borderBottom:`1px solid ${C.bdr}`}}>
                        {['#','Ticker','Name','Category','Score','Yield','Div Growth','Streak','Drawdown'].map(h=>(
                          <th key={h} style={{padding:'8px 12px',textAlign:['#','Ticker','Name','Category'].includes(h)?'left':'right',color:C.muted,fontWeight:600,whiteSpace:'nowrap'}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_candidates.map((c,i)=>(
                        <tr key={c.ticker} style={{borderBottom:`1px solid ${C.bdr}22`}}>
                          <td style={{padding:'7px 12px',color:C.muted}}>{i+1}</td>
                          <td style={{padding:'7px 12px',fontWeight:700,color:C.text}}>{c.ticker}</td>
                          <td style={{padding:'7px 12px',color:C.sub}}>{c.name}</td>
                          <td style={{padding:'7px 12px'}}>
                            <span style={{fontSize:'11px',color:CAT_COLOR[c.category]||C.muted,background:`${CAT_COLOR[c.category]||C.muted}22`,padding:'1px 6px',borderRadius:'4px'}}>
                              {CAT_LABEL[c.category]||c.category}
                            </span>
                          </td>
                          <td style={{padding:'7px 12px',textAlign:'right',color:c.score>=75?C.accent:C.sub,fontWeight:600}}>{c.score}</td>
                          <td style={{padding:'7px 12px',textAlign:'right',color:C.accent}}>{fmtP(c.annual_yield_pct)}</td>
                          <td style={{padding:'7px 12px',textAlign:'right',color:c.div_growth_pct>=0?C.accent:C.red}}>
                            {c.div_growth_pct>0?'+':''}{c.div_growth_pct?.toFixed(1)}%</td>
                          <td style={{padding:'7px 12px',textAlign:'right',color:C.sub}}>{c.streak_payments}</td>
                          <td style={{padding:'7px 12px',textAlign:'right',color:c.drawdown_from_high_pct>20?C.red:C.sub}}>
                            -{c.drawdown_from_high_pct?.toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div style={{fontSize:'12px',color:C.muted,textAlign:'center',paddingBottom:'8px'}}>
            Price and dividend data via Polygon. Projections assume 5% annual price appreciation, DRIP reinvestment, and historical dividend growth rate.
            Past performance does not guarantee future results. Scanned {activeData.scanned_at?new Date(activeData.scanned_at).toLocaleString():'—'}.
          </div>
        </>
      )}

      {/* ── DIVIDEND SCREENER ────────────────────────────────────────────── */}
      <DividendScreener />
    </div>
  )
}

function DividendScreener() {
  const [data, setData] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [collapsed, setCollapsed] = useState(true)
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const fetchResults = async () => {
    try {
      const res = await fetch('/api/advanced-scanner/dividend')
      if (!res.ok) return
      const body = await res.json().catch(() => ({}))
      if (body.scanning) {
        startPolling()
      } else {
        setData(body)
        stopPolling()
        setScanning(false)
      }
    } catch {}
  }

  const startPolling = () => {
    if (pollRef.current) return
    setScanning(true)
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch('/api/advanced-scanner/status/dividend')
        if (!res.ok) return
        const body = await res.json().catch(() => ({}))
        if (!body.running) {
          stopPolling()
          setScanning(false)
          fetchResults()
        }
      } catch {}
    }, 2500)
  }

  useEffect(() => {
    fetchResults()
    return () => stopPolling()
  }, []) // eslint-disable-line

  const handleRefresh = async () => {
    setData(null)
    setCollapsed(false)
    try {
      await fetch('/api/advanced-scanner/refresh/dividend', { method: 'POST' })
      startPolling()
    } catch {}
  }

  const results = data?.results || []

  return (
    <div style={{background:C.card,border:`1px solid ${C.bdr}`,borderRadius:'12px',overflow:'hidden',marginTop:'8px'}}>
      <div style={{padding:'14px 20px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
        <div>
          <span style={{fontSize:'14px',fontWeight:600,color:C.text}}>💰 Dividend Income Screener</span>
          <span style={{fontSize:'11px',color:C.muted,marginLeft:'10px'}}>High-yield growers · Nasdaq Dividend Achievers universe</span>
          {data?.scanned_at && <span style={{fontSize:'11px',color:'#4a5568',marginLeft:'8px'}}>· {Math.floor((Date.now()-new Date(data.scanned_at))/3600000)}h ago</span>}
        </div>
        <div style={{display:'flex',gap:'8px'}}>
          <button
            onClick={handleRefresh}
            disabled={scanning}
            style={{padding:'5px 12px',background:scanning?'#2d3748':'#1a2a1a',color:scanning?C.muted:C.accent,border:`1px solid ${scanning?'#2d3748':'#2f855a'}`,borderRadius:'6px',cursor:scanning?'not-allowed':'pointer',fontSize:'11px',fontWeight:600}}
          >
            {scanning ? '⟳ Scanning…' : '⟳ Refresh'}
          </button>
          <button onClick={() => setCollapsed(s => !s)} style={{padding:'5px 12px',background:'transparent',border:`1px solid ${C.bdr}`,borderRadius:'6px',color:C.sub,cursor:'pointer',fontSize:'13px'}}>
            {collapsed ? 'Show' : 'Hide'}
          </button>
        </div>
      </div>
      {!collapsed && (
        <div style={{borderTop:`1px solid ${C.bdr}`,padding:'16px 20px'}}>
          {scanning && (
            <div style={{marginBottom:'16px'}}>
              <div style={{fontSize:'12px',color:C.accent,marginBottom:'8px'}}>Scanning dividend growers…</div>
              <div style={{height:'6px',background:'#2d3748',borderRadius:'3px',overflow:'hidden'}}>
                <div style={{width:'50%',height:'100%',background:`linear-gradient(90deg,#276749,#48bb78)`,borderRadius:'3px'}}/>
              </div>
            </div>
          )}
          {results.length > 0 ? (
            <div style={{display:'flex',flexDirection:'column',gap:'8px'}}>
              {results.slice(0,10).map((r, i) => (
                <div key={r.ticker} style={{display:'flex',alignItems:'center',gap:'10px',padding:'10px 12px',background:'#0f1117',border:`1px solid ${C.bdr}`,borderRadius:'8px',flexWrap:'wrap'}}>
                  <span style={{fontSize:'12px',color:C.muted,minWidth:'22px'}}>#{i+1}</span>
                  <span style={{fontSize:'15px',fontWeight:800,color:C.text,minWidth:'52px'}}>{r.ticker}</span>
                  <span style={{fontSize:'12px',color:C.muted,flex:1}}>{r.name||''}</span>
                  {r.dividend_yield_pct != null && <span style={{padding:'2px 8px',borderRadius:'5px',fontSize:'11px',fontWeight:700,background:'#1a2a1a',color:C.accent}}>{Number(r.dividend_yield_pct).toFixed(1)}% yield</span>}
                  {r.dcf_base_upside != null && <span style={{padding:'2px 8px',borderRadius:'5px',fontSize:'11px',background:'#1a2a3a',color:'#90cdf4'}}>Base {r.dcf_base_upside > 0 ? '+' : ''}{Number(r.dcf_base_upside).toFixed(0)}%</span>}
                  <span style={{padding:'2px 8px',borderRadius:'5px',fontSize:'11px',fontWeight:700,background:'#1a3a2a',color:C.accent}}>{r.trigger_score ?? '—'}/8</span>
                </div>
              ))}
            </div>
          ) : !scanning && (
            <div style={{textAlign:'center',color:C.muted,padding:'32px',fontSize:'13px'}}>
              No results — click Refresh to run a fresh scan.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
