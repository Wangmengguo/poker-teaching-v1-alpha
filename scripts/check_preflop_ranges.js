#!/usr/bin/env node
/*
  Usage: node scripts/check_preflop_ranges.js --dir packages/poker_core/suggest/config

  Outputs JSON and human-readable summary for:
  - RFI % (169-grid and combos-weighted)
  - Defend % per bucket {small,mid,large} (combos-weighted, union of call∪reraise)
  - 3bet share per bucket = reraise / (call∪reraise)
  - Monotonicity checks: loose ⊇ medium ⊇ tight (per open/call/raise), small ⊇ mid ⊇ large (per call/raise)
  - Label validity / duplicates / missing keys

  Exit code 1 on failed checks when targets are provided via env or default gates.
*/

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
let baseDir = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--dir') baseDir = args[i + 1];
}
if (!baseDir) {
  console.error('Usage: node scripts/check_preflop_ranges.js --dir <config_dir>');
  process.exit(2);
}

const STRATS = ['loose','medium','tight'];
const BUCKETS = ['small','mid','large'];
const GRID_TOTAL = 169; // 13 pairs + 78 suited + 78 offsuit
const COMBOS_TOTAL = 1326;

const RANKS = ['A','K','Q','J','T','9','8','7','6','5','4','3','2'];
const RANK_INDEX = Object.fromEntries(RANKS.map((r,i)=>[r,i]));

function isValidLabel(lbl){
  if (typeof lbl !== 'string') return false;
  lbl = lbl.trim();
  if (!lbl) return false;
  // Pair
  if (/^(AA|KK|QQ|JJ|TT|99|88|77|66|55|44|33|22)$/.test(lbl)) return true;
  // Suited/offsuit like AKs, QTo
  const m = /^([AKQJT98765432])([KQJT98765432])(s|o)$/.exec(lbl);
  if (!m) return false;
  const a = m[1], b = m[2];
  if (a === b) return false; // pairs must be 2-char form
  // enforce high-first ordering by rank precedence A>K>...>2
  if (RANK_INDEX[a] > RANK_INDEX[b]) return false;
  return true;
}

function combosOf(lbl){
  if (/^(AA|KK|QQ|JJ|TT|99|88|77|66|55|44|33|22)$/.test(lbl)) return 6;
  if (/s$/.test(lbl)) return 4;
  if (/o$/.test(lbl)) return 12;
  return 0;
}

function loadJSON(p){
  return JSON.parse(fs.readFileSync(p,'utf8'));
}

function setFromArray(arr){
  const s = new Set();
  for (const x of (arr||[])) if (x) s.add(String(x));
  return s;
}

function unionSizeByCombos(aSet,bSet){
  // union on labels, then sum combos
  const u = new Set([...aSet, ...bSet]);
  let c=0; u.forEach(x=>c+=combosOf(x));
  return c;
}

function sumCombos(aSet){
  let c=0; aSet.forEach(x=>c+=combosOf(x));
  return c;
}

function countInvalid(arr){
  const invalid=[]; const seen=new Set(); const dups=[];
  for (const x of arr||[]) {
    if (!isValidLabel(x)) invalid.push(x);
    const k=String(x);
    if (seen.has(k)) dups.push(k);
    seen.add(k);
  }
  return {invalid,dups};
}

function readStrategy(dir,strat){
  const open = loadJSON(path.join(dir,'ranges',`preflop_open_HU_${strat}.json`));
  const vs = loadJSON(path.join(dir,'ranges',`preflop_vs_raise_HU_${strat}.json`));
  const modes = loadJSON(path.join(dir,`table_modes_${strat}.json`));
  return {open,vs,modes};
}

function rfiStats(open){
  const sbArr = open.SB || [];
  const grid = sbArr.length / GRID_TOTAL;
  const {invalid,dups} = countInvalid(sbArr);
  let combos = 0; sbArr.forEach(x=>combos+=combosOf(x));
  return {
    grid_pct: grid,
    combos_pct: combos/COMBOS_TOTAL,
    sb_count: sbArr.length,
    combos,
    invalid,dups
  };
}

function defendStats(vs){
  const node = vs['BB_vs_SB'] || {};
  const out={};
  for (const b of BUCKETS){
    const obj = node[b] || {};
    const call = setFromArray(obj.call||[]);
    const raise = setFromArray(obj.reraise||[]);
    // overlap on labels
    const inter = new Set([...call].filter(x=>raise.has(x)));
    const uni = new Set([...call, ...raise]);
    const overlap_pct = (uni.size>0) ? (inter.size/uni.size) : 0;
    const defendCombos = unionSizeByCombos(call,raise);
    const raiseCombos = sumCombos(raise);
    out[b] = {
      defend_pct: defendCombos/COMBOS_TOTAL,
      threebet_share: defendCombos>0 ? (raiseCombos/defendCombos) : 0,
      call_count: call.size,
      raise_count: raise.size,
      call_combos: sumCombos(call),
      raise_combos: raiseCombos,
      overlap_pct,
      overlap_count: inter.size,
      union_count: uni.size,
      overlap_examples: [...inter].slice(0, 8),
      invalid: [...call,...raise].filter(x=>!isValidLabel(x)),
      // store raw sets for monotonic checks
      _call: call,
      _raise: raise,
    };
  }
  return out;
}

function monotonicSuperset(aSet,bSet){
  for (const x of bSet) if (!aSet.has(x)) return false;
  return true;
}

function checkMonotonicAcrossBuckets(stats){
  const errs=[];
  // small ⊇ mid ⊇ large for call/raise separately
  const s=stats.small, m=stats.mid, l=stats.large;
  if (!monotonicSuperset(s._call, m._call)) errs.push('call: small ⊇ mid violated');
  if (!monotonicSuperset(m._call, l._call)) errs.push('call: mid ⊇ large violated');
  if (!monotonicSuperset(s._raise, m._raise)) errs.push('raise: small ⊇ mid violated');
  if (!monotonicSuperset(m._raise, l._raise)) errs.push('raise: mid ⊇ large violated');
  return errs;
}

function checkMonotonicAcrossStrats(data){
  const errs=[];
  // open: loose ⊇ medium ⊇ tight
  const openLoose = new Set(data.loose.open.SB||[]);
  const openMed = new Set(data.medium.open.SB||[]);
  const openTight = new Set(data.tight.open.SB||[]);
  if (!monotonicSuperset(openLoose, openMed)) errs.push('open: loose ⊇ medium violated');
  if (!monotonicSuperset(openMed, openTight)) errs.push('open: medium ⊇ tight violated');
  // vs buckets for call/raise
  for (const b of BUCKETS){
    const L = data.loose.defend[b], M = data.medium.defend[b], T = data.tight.defend[b];
    if (!monotonicSuperset(L._call, M._call)) errs.push(`call.${b}: loose ⊇ medium violated`);
    if (!monotonicSuperset(M._call, T._call)) errs.push(`call.${b}: medium ⊇ tight violated`);
    if (!monotonicSuperset(L._raise, M._raise)) errs.push(`raise.${b}: loose ⊇ medium violated`);
    if (!monotonicSuperset(M._raise, T._raise)) errs.push(`raise.${b}: medium ⊇ tight violated`);
  }
  return errs;
}

function pct(x){return (100*x).toFixed(1)+'%';}

function main(){
  const cfg = {};
  for (const s of STRATS){ cfg[s]=readStrategy(baseDir,s); }

  const out = {};
  for (const s of STRATS){
    const rfi = rfiStats(cfg[s].open);
    const defend = defendStats(cfg[s].vs);
    out[s]={rfi,defend};
  }

  const only = (process.env.CHECK_ONLY_STRATEGY||'').toLowerCase();
  const bucketMonoErrs = {};
  for (const s of STRATS){
    bucketMonoErrs[s] = checkMonotonicAcrossBuckets(out[s].defend);
  }
  const stratMonoErrs = (only
    ? []
    : checkMonotonicAcrossStrats({
        loose: {open: cfg.loose.open, defend: out.loose.defend},
        medium:{open: cfg.medium.open, defend: out.medium.defend},
        tight: {open: cfg.tight.open, defend: out.tight.defend},
      })
  );

  // targets (only validate medium by default)
  const targets = {
    medium: {
      rfi_grid_min: 0.70, rfi_grid_max: 0.74,
      defend_small: {min: 0.49, max: 0.51, threebet_share_min: 0.10, threebet_share_max: 0.14},
      defend_mid_drop: {min: 0.10, max: 0.15},
      defend_large_drop: {min: 0.10, max: 0.15},
    }
  };

  // compute drops from small for medium
  const med = out.medium.defend;
  const small = med.small.defend_pct;
  const mid = med.mid.defend_pct;
  const large = med.large.defend_pct;
  const drops = {mid: (small-mid), large: (mid-large)};

  const fails=[];
  // RFI grid target
  if (!(out.medium.rfi.grid_pct >= targets.medium.rfi_grid_min && out.medium.rfi.grid_pct <= targets.medium.rfi_grid_max))
    fails.push(`medium.RFI.grid=${pct(out.medium.rfi.grid_pct)} not in [${pct(targets.medium.rfi_grid_min)}, ${pct(targets.medium.rfi_grid_max)}]`);
  // small defend & 3bet share
  if (!(small >= targets.medium.defend_small.min && small <= targets.medium.defend_small.max))
    fails.push(`medium.defend.small=${pct(small)} not in [${pct(targets.medium.defend_small.min)}, ${pct(targets.medium.defend_small.max)}]`);
  if (!(med.small.threebet_share >= targets.medium.defend_small.threebet_share_min && med.small.threebet_share <= targets.medium.defend_small.threebet_share_max))
    fails.push(`medium.small.3bet_share=${(100*med.small.threebet_share).toFixed(1)}% not in [${(100*targets.medium.defend_small.threebet_share_min).toFixed(1)}%, ${(100*targets.medium.defend_small.threebet_share_max).toFixed(1)}%]`);
  // bucket drops
  if (!(drops.mid >= targets.medium.defend_mid_drop.min && drops.mid <= targets.medium.defend_mid_drop.max))
    fails.push(`medium.drop.mid=${pct(drops.mid)} not in [${pct(targets.medium.defend_mid_drop.min)}, ${pct(targets.medium.defend_mid_drop.max)}]`);
  if (!(drops.large >= targets.medium.defend_large_drop.min && drops.large <= targets.medium.defend_large_drop.max))
    fails.push(`medium.drop.large=${pct(drops.large)} not in [${pct(targets.medium.defend_large_drop.min)}, ${pct(targets.medium.defend_large_drop.max)}]`);

  // monotonic errors
  if (only){
    for (const e of bucketMonoErrs[only]||[]) fails.push(`${only}.buckets: ${e}`);
  } else {
    for (const s of STRATS){
      for (const e of bucketMonoErrs[s]) fails.push(`${s}.buckets: ${e}`);
    }
    for (const e of stratMonoErrs) fails.push(`strats: ${e}`);
  }

  const summary = {
    baseDir,
    results: out,
    bucketMonotonicErrors: bucketMonoErrs,
    stratMonotonicErrors: stratMonoErrs,
    fails,
  };
  // console summary
  const show = only ? [only] : STRATS;
  for (const s of show){
    const r = out[s];
    console.log(`\n[${s}] RFI grid=${pct(r.rfi.grid_pct)}, combos=${pct(r.rfi.combos_pct)} (count=${r.rfi.sb_count})`);
    for (const b of BUCKETS){
      const d = r.defend[b];
      const ov = (100*d.overlap_pct).toFixed(1)+'%';
      const ovFlag = d.overlap_pct>=0.15 ? ' [WARN overlap]' : (d.overlap_pct>=0.08 ? ' [hint overlap]' : '');
      console.log(
        `  ${b}: defend=${pct(d.defend_pct)} (combos ${d.call_combos+d.raise_combos}/${COMBOS_TOTAL}),`+
        ` 3bet share ${(100*d.threebet_share).toFixed(1)}% (3bet combos ${d.raise_combos}),`+
        ` call#=${d.call_count}, raise#=${d.raise_count}, overlap=${ov}${ovFlag}`
      );
    }
  }

  // Boundary self-checks (print-only)
  try {
    const med = cfg.medium; const tig = cfg.tight;
    const toBucket = (open_to_bb)=> (open_to_bb<=2.5?'small':(open_to_bb<=4?'mid':'large'));
    // Case 1: SB 4x, KQo → medium OK, tight BAD
    const b1 = toBucket(4.0);
    const med1 = new Set([...(med.vs.BB_vs_SB?.[b1]?.call||[]),...(med.vs.BB_vs_SB?.[b1]?.reraise||[])]);
    const tig1 = new Set([...(tig.vs.BB_vs_SB?.[b1]?.call||[]),...(tig.vs.BB_vs_SB?.[b1]?.reraise||[])]);
    const medOK = med1.has('KQo');
    const tigBAD = !tig1.has('KQo');
    console.log(`\n[boundary] SB open_to=4.0bb, hand=KQo, bucket=${b1} → medium=${medOK?'OK':'BAD'}, tight=${tigBAD?'BAD':'OK'}`);

    // Case 2: SB 4.5x, ATs → both BAD expected
    const b2 = toBucket(4.5);
    const med2 = new Set([...(med.vs.BB_vs_SB?.[b2]?.call||[]),...(med.vs.BB_vs_SB?.[b2]?.reraise||[])]);
    const tig2 = new Set([...(tig.vs.BB_vs_SB?.[b2]?.call||[]),...(tig.vs.BB_vs_SB?.[b2]?.reraise||[])]);
    const medAT = med2.has('ATs');
    const tigAT = tig2.has('ATs');
    console.log(`[boundary] SB open_to=4.5bb, hand=ATs, bucket=${b2} → medium=${medAT?'OK':'BAD'}, tight=${tigAT?'OK':'BAD'}`);

    // Unit sample: compute pot_odds for open_to=4.0 and 4.5
    const potOdds = (open_to)=>{ const to_call=open_to-1; const pot_now=open_to+1; return to_call/(pot_now+to_call); };
    console.log(`[units] open_to=4.0 → to_call_bb=3.0, pot_odds=${potOdds(4.0).toFixed(4)}`);
    console.log(`[units] open_to=4.5 → to_call_bb=3.5, pot_odds=${potOdds(4.5).toFixed(4)}`);
  } catch (e) {
    console.log('[boundary] self-check skipped:', e?.message||String(e));
  }

  // Optional: parse debug samples to estimate W_CLAMPED / min-reopen rates
  try {
    const samplePath = process.env.SUGGEST_DEBUG_SAMPLES;
    if (samplePath && fs.existsSync(samplePath)){
      const lines = fs.readFileSync(samplePath, 'utf8').split(/\r?\n/).filter(Boolean);
      let n=0, wClamp=0, minReopen3=0, minReopen4=0, raises=0;
      for (const ln of lines){
        let obj=null;
        try { obj = JSON.parse(ln); } catch {_skip: continue}
        if (!obj || !obj.rationale) continue;
        n++;
        const codes = new Set((obj.rationale||[]).map(x=>x && x.code).filter(Boolean));
        if ((obj.suggested||{}).action==='raise') raises++;
        if (codes.has('W_CLAMPED')) wClamp++;
        if (codes.has('PF_DEFEND_3BET_MIN_RAISE_ADJUSTED')) minReopen3++;
        if (codes.has('PF_ATTACK_4BET_MIN_RAISE_ADJUSTED')) minReopen4++;
      }
      const rate = (x)=> (n? (100*x/n).toFixed(2)+'%':'n/a');
      const rRaise = (x)=> (raises? (100*x/raises).toFixed(2)+'%':'n/a');
      console.log(`\n[samples] total=${n}, raises=${raises}, W_CLAMPED=${wClamp} (${rate(wClamp)}, among raises ${rRaise(wClamp)})`);
      console.log(`[samples] min_reopen_3bet=${minReopen3} (${rate(minReopen3)}) | min_reopen_4bet=${minReopen4} (${rate(minReopen4)})`);
    } else {
      console.log('\n[samples] no sample file (set SUGGEST_DEBUG_SAMPLES=/path/to/jsonl)');
    }
  } catch (e) {
    console.log('[samples] parsing error:', e?.message||String(e));
  }
  if (fails.length){
    console.error('\nCHECK FAILED:');
    for (const f of fails) console.error(' -', f);
    console.log('\nJSON Output:\n'+JSON.stringify(summary,null,2));
    process.exit(1);
  }
  console.log('\nAll checks passed.');
  console.log('\nJSON Output:\n'+JSON.stringify(summary,null,2));
}

main();
