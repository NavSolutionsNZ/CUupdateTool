#!/usr/bin/env python3
"""Anchor scorer v6 — position-validated, structural-boundary-aware.

Fixes the two known false-positive bugs:
  BUG1: vendor-tag anchor matched globally (key exists anywhere in B) -> now must be
        positionally coherent: before+after anchors found in B with the after FOLLOWING
        the before within a bounded window, AND no structural boundary crossed.
  BUG2: overridden-original matched globally -> now validated AT the anchored position only.

Structural boundary = procedure/trigger/field delimiter. Anchors may not be sought across a
boundary the block sits inside (prevents anchoring onto an unrelated surviving region when the
block's own enclosing procedure is customer-authored & absent from B).
"""
import re
from difflib import SequenceMatcher

def build_grammar(prefixes):
    alt='|'.join(sorted(prefixes,key=len,reverse=True))
    return (re.compile(rf'^\s*//\s*Start\s+({alt})([0-9.\-]*)\b',re.I),
            re.compile(rf'^\s*//\s*Stop\s+({alt})([0-9.\-]*)\b',re.I))

def norm(l): return re.sub(r'\s+',' ',l.strip())
def sim(a,b): return 1.0 if a==b else SequenceMatcher(None,a,b).ratio()
BOILER=re.compile(r'^(BEGIN|END;?|END\.|\{|\}|VAR|)$',re.I)
CC=re.compile(r'^\s*//\s*[A-Za-z"\(]')   # commented-out code (vanilla-mod signal)
# structural boundaries in C/AL txt: PROCEDURE / trigger props / field def lines / section headers
BOUNDARY=re.compile(r'^\s*(LOCAL\s+)?PROCEDURE\b|^\s*\{\s*\d+\s*;|^\s*(PROPERTIES|FIELDS|KEYS|CONTROLS|CODE|DATASET|REQUESTPAGE|ELEMENTS)\s*$|@\d+\s*:\s*(Page|Record|Codeunit|Report)',re.I)

def load(fn): return open(fn,encoding='latin-1').read().replace('\r\n','\n').split('\n')

class Scorer:
    def __init__(self, custfn, vendfn, customer_prefixes, all_prefixes):
        self.OPEN,self.CLOSE=build_grammar(all_prefixes)
        self.A=load(custfn); self.B=load(vendfn)
        self.bn=[norm(x) for x in self.B]
        self.CUST=customer_prefixes
        # index vendor-tag keys -> positions in B
        self.Bvt={}
        for i,l in enumerate(self.B):
            k=self._vkey(l)
            if k: self.Bvt.setdefault(k,[]).append(i)
    def _vkey(self,l):
        m=self.OPEN.match(l) or self.CLOSE.match(l)
        return f"{m.group(1).upper()}{m.group(2)}" if (m and m.group(1).upper() not in self.CUST) else None
    def is_tag(self,l): return bool(self.OPEN.match(l) or self.CLOSE.match(l))

    def blocks(self):
        st=[];out=[]
        for i,l in enumerate(self.A):
            mo=self.OPEN.match(l);mc=self.CLOSE.match(l)
            if mo and mo.group(1).upper() in self.CUST: st.append({'p':mo.group(1).upper(),'id':mo.group(2),'start':i})
            elif mc and mc.group(1).upper() in self.CUST:
                for k in range(len(st)-1,-1,-1):
                    if st[k]['p']==mc.group(1).upper() and st[k]['id']==mc.group(2):
                        b=st.pop(k);b['stop']=i;b['inner']=self.A[b['start']+1:i];out.append(b);break
        return out

    def _anchor(self, idx, step):
        """walk outward but STOP at a structural boundary. prefer vendor tag, else distinctive code."""
        j=idx; code=None
        for _ in range(30):
            j+=step
            if j<0 or j>=len(self.A): break
            line=self.A[j]
            # boundary check: if we hit a boundary, stop searching outward past it
            if BOUNDARY.match(line):
                # the boundary line itself can be an anchor if distinctive & in B
                k=self._vkey(line)
                if k and k in self.Bvt: return ('vtag',k)
                n=norm(line)
                if n and not BOILER.match(n): return ('boundary',n)
                return code or ('none',None)
            k=self._vkey(line)
            if k and k in self.Bvt: return ('vtag',k)
            n=norm(line)
            if n and not BOILER.match(n) and not self.is_tag(line) and code is None:
                code=('code',n)
        return code or ('none',None)

    def _locate(self,kind,val):
        if kind=='vtag': return self.Bvt.get(val,[])
        if kind in ('code','boundary'):
            return [i for i,x in enumerate(self.bn) if sim(val,x)>=0.90]
        return []

    def _classify(self,inner):
        real=[x for x in inner if norm(x) and not self.is_tag(x) and not CC.match(x)]
        commented=[x for x in inner if CC.match(x) and not self.is_tag(x)]
        if commented and not real: return 'VANILLA_SUPPRESS'   # commented vendor out, no replacement
        if commented and real:     return 'VANILLA_MOD'        # commented original + replacement
        return 'PURE_ADD'

    def score_block(self,b):
        content=self._classify(b['inner'])
        vmod=(content=='VANILLA_MOD')
        bk,bv=self._anchor(b['start'],-1); ak,av=self._anchor(b['stop'],+1)
        bpos=self._locate(bk,bv); apos=self._locate(ak,av)
        # POSITION VALIDATION: after must follow before within a bounded window in B
        coherent=False; chosen=None
        block_span=(b['stop']-b['start'])+1
        window=block_span+15
        for pb in sorted(bpos):
            cand=[pa for pa in apos if 0 < pa-pb <= window]
            if cand: coherent=True; chosen=(pb,min(cand)); break
        type_w={'vtag':1.0,'boundary':0.75,'code':0.6,'none':0.0}
        score=(type_w[bk]+type_w[ak])/2 if coherent else 0.0

        orig_ok=None
        if vmod and coherent and chosen:
            # validate overridden original AT the anchored region only (pb..pa), not globally
            pb,pa=chosen
            region=self.bn[pb:pa+1]
            orig_ok=False
            for x in b['inner']:
                if CC.match(x) and not self.is_tag(x):
                    o=norm(re.sub(r'^\s*//\s*','',x))
                    if any(sim(o,y)>=0.95 for y in region): orig_ok=True
        # verdict
        PURE_T=0.75; VMOD_T=0.90
        if content=='PURE_ADD':
            verdict='TRANSPLANT' if score>=PURE_T else 'DEV'
        elif content=='VANILLA_SUPPRESS':
            verdict='DEV'   # suppressing vendor logic is always a human decision
        else:  # VANILLA_MOD
            verdict='TRANSPLANT' if (score>=VMOD_T and orig_ok) else 'DEV'
        return dict(tag=f"{b['p']}{b['id']}",line=b['start']+1,content=content,
                    score=round(score,2),coherent=coherent,anchors=(bk,ak),orig_ok=orig_ok,verdict=verdict)

OBJS=[('T36','Cust_T36.txt','20206Q1_T36.txt'),('C80','Cust_C80.txt','20206Q1_C80.txt'),
      ('R790','Cust_R790.txt','20206Q1_R790.txt'),('T14','Cust_T14.txt','20206Q1_T14.txt'),
      ('T38','Cust_T38.txt','20206Q1_T38.txt'),('T39','Cust_T39.txt','20206Q1_T39.txt'),
      ('T5025400','Cust_T5025400.txt','20206Q1_T5025400.txt')]
CUST={'AP','WBL'}; ALL={'AP','WBL','PA','PPA','EU','INC','IMM','PS'}

if __name__=='__main__':
    for name,a,b in OBJS:
        s=Scorer(a,b,CUST,ALL)
        print(f"\n#### {name}")
        for blk in s.blocks():
            r=s.score_block(blk)
            print(f"  [{r['tag']}@{r['line']}] {r['content']} score={r['score']} "
                  f"coh={r['coherent']} anch={r['anchors']} "
                  f"{'orig='+str(r['orig_ok']) if r['content']=='VANILLA_MOD' else ''} -> {r['verdict']}")
