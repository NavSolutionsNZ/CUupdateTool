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
    # incadea tags come in two comment styles, both standard:
    #   line-comment:  // Start <tag> ... // Stop <tag>
    #   block-comment: { Start <tag>  ...   Stop <tag>}   (braces = C/AL block comment delimiters)
    alt='|'.join(sorted(prefixes,key=len,reverse=True))
    return (re.compile(rf'^\s*(?://|\{{)\s*Start\s+({alt})([0-9.\-]*)\b',re.I),
            re.compile(rf'^\s*(?://\s*)?Stop\s+({alt})([0-9.\-]*)\s*\}}?',re.I))

def norm(l): return re.sub(r'\s+',' ',l.strip())
def sim(a,b): return 1.0 if a==b else SequenceMatcher(None,a,b).ratio()
BOILER=re.compile(r'^(BEGIN|END;?|END\.|\{|\}|VAR|)$',re.I)
CC=re.compile(r'^\s*//\s*[A-Za-z"\(]')   # commented-out code (vanilla-mod signal)
# structural boundaries in C/AL txt: PROCEDURE / trigger props / field def lines / section headers
BOUNDARY=re.compile(r'^\s*(LOCAL\s+)?PROCEDURE\b|^\s*\{\s*\d+\s*;|^\s*(PROPERTIES|FIELDS|KEYS|CONTROLS|CODE|DATASET|REQUESTPAGE|ELEMENTS)\s*$|@\d+\s*:\s*(Page|Record|Codeunit|Report)',re.I)

def load(fn): return open(fn,encoding='latin-1').read().replace('\r\n','\n').split('\n')

# ---- shared procedure-unit parser (used by BOTH scorer and diffengine) ------
# Single source of truth so the two modules can't drift. Identity is name@id.
_PROC_NAME=re.compile(r'^    (?:LOCAL )?PROCEDURE\s+(\w+)@(\d+)\s*\(')
_ATTR_LINE=re.compile(r'^    \[[A-Za-z][\w ]*\]\s*$')

def parse_proc_units(lines):
    """Return {name@id: {'name','id','start','end','local','text'}} for every
    CODE-section procedure. 'start' is the attribute line if one directly
    precedes the signature, else the signature line; 'end' is the index of the
    procedure's terminating END; (inclusive); 'text' is the verbatim slice;
    'local' is True for LOCAL PROCEDURE. Identity is name@id, so a customer
    procedure absent from B is detectable by key difference.

    Boundary detection uses C/AL's fixed indentation: a procedure body is
    opened by BEGIN at 4-space indent ('    BEGIN') and closed by END; at
    4-space indent ('    END;'). Inner BEGIN/END (IF..THEN BEGIN, END ELSE
    BEGIN, CASE..END) are always indented deeper, so this avoids the
    END-ELSE-BEGIN depth-underflow that token counting hits. The object
    trigger closes with '    END.' (dot), which is not a procedure."""
    units={}; i=0; n=len(lines)
    while i<n:
        pm=_PROC_NAME.match(lines[i])
        if pm:
            name,pid=pm.group(1),pm.group(2)
            start=i
            if i-1>=0 and _ATTR_LINE.match(lines[i-1]):
                start=i-1
            local=lines[i].lstrip().startswith('LOCAL')
            # find the proc-level BEGIN ('    BEGIN'), then the next
            # proc-level END; ('    END;') closes the procedure.
            j=i+1; seen_begin=False
            while j<n:
                l=lines[j]
                if not seen_begin:
                    if l=='    BEGIN': seen_begin=True
                    # a following PROCEDURE before any BEGIN => malformed;
                    # bail so we don't swallow the next procedure.
                    elif _PROC_NAME.match(l): j-=1; break
                else:
                    if l=='    END;' or l=='    END.': break
                j+=1
            units[f'{name}@{pid}']={'name':name,'id':pid,'start':start,'end':j,
                                    'local':local,'text':'\n'.join(lines[start:j+1])}
            i=j+1; continue
        i+=1
    return units

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
        # procedure-unit maps for A and B (identity = name@id). Used to confine
        # a CODE-section block's anchor search to its OWN enclosing procedure,
        # so a vendor-boilerplate anchor (e.g. '// Start PA036544') that recurs
        # across several procedures can't graft the block into the wrong one.
        self.Aproc=self._proc_units(self.A)
        self.Bproc=self._proc_units(self.B)
        # B-procedure lookup by id and by name (id is the durable C/AL identity;
        # vendors rename-without-renumber, so id wins, name is the fallback key).
        self.Bproc_by_id={}; self.Bproc_by_name={}
        for key,u in self.Bproc.items():
            self.Bproc_by_id[u['id']]=u
            self.Bproc_by_name.setdefault(u['name'],u)

    # ---- procedure-unit parsing (delegates to module-level parse_proc_units,
    #      shared with diffengine so the two cannot drift) -------------------
    def _proc_units(self, lines):
        return parse_proc_units(lines)

    def _a_enclosing(self, idx):
        """The A-procedure unit containing A-line idx, or None if idx lies
        outside any procedure (global VAR / object trigger scope)."""
        for u in self.Aproc.values():
            if u['start']<=idx<=u['end']:
                return u
        return None

    def _b_match(self, a_unit):
        """Resolve a_unit's matching B-procedure: by id first, name fallback.
        Returns the B unit or None (vendor removed/renamed-and-renumbered)."""
        u=self.Bproc_by_id.get(a_unit['id'])
        if u is not None: return u
        return self.Bproc_by_name.get(a_unit['name'])
    def _vkey(self,l):
        m=self.OPEN.match(l) or self.CLOSE.match(l)
        return f"{m.group(1).upper()}{m.group(2)}" if (m and m.group(1).upper() not in self.CUST) else None
    def is_tag(self,l): return bool(self.OPEN.match(l) or self.CLOSE.match(l))

    def blocks(self):
        st=[];out=[]
        for i,l in enumerate(self.A):
            mo=self.OPEN.match(l);mc=self.CLOSE.match(l)
            if mo and mo.group(1).upper() in self.CUST:
                brace = l.lstrip().startswith('{')   # block-comment style => inner is suppressed vendor code
                st.append({'p':mo.group(1).upper(),'id':mo.group(2),'start':i,'brace':brace})
            elif mc and mc.group(1).upper() in self.CUST:
                for k in range(len(st)-1,-1,-1):
                    if st[k]['p']==mc.group(1).upper() and st[k]['id']==mc.group(2):
                        b=st.pop(k);b['stop']=i;b['inner']=self.A[b['start']+1:i];out.append(b);break
        return out

    def _anchor(self, idx, step):
        """Walk outward but STOP at a structural boundary. Return the best
        anchor by NEARNESS, with a tie/quality preference for vendor tags.

        Both extremes were wrong: always preferring a vendor tag mis-anchored
        blocks whose immediate neighbour is a strong non-vtag marker (e.g.
        '//INC2.00') while a reused vtag sat several lines further out; always
        taking the nearest line latched onto weak, ambiguous code lines. So we
        record the nearest distinctive code line AND the nearest vtag, then
        prefer the vtag only when it is at least as near as the code line
        (vtags are more reliable, but not worth reaching far past a closer,
        equally distinctive neighbour)."""
        j=idx
        code=None; code_d=None       # nearest distinctive code line + its distance
        for d in range(1, 31):
            j+=step
            if j<0 or j>=len(self.A): break
            line=self.A[j]
            if BOUNDARY.match(line):
                # boundary terminates the search; it may itself anchor
                k=self._vkey(line)
                if k and k in self.Bvt:
                    if code is not None and code_d < d: return ('code', code)
                    return ('vtag', k)
                n=norm(line)
                if code is not None: return ('code', code)
                if n and not BOILER.match(n): return ('boundary', n)
                return ('none', None)
            k=self._vkey(line)
            if k and k in self.Bvt:
                # vtag here: prefer a strictly-nearer code anchor if we have one
                if code is not None and code_d < d: return ('code', code)
                return ('vtag', k)
            n=norm(line)
            if n and not BOILER.match(n) and not self.is_tag(line) and code is None:
                code=n; code_d=d
        return ('code', code) if code is not None else ('none', None)

    def _locate(self,kind,val):
        if kind=='vtag': return self.Bvt.get(val,[])
        if kind in ('code','boundary'):
            return [i for i,x in enumerate(self.bn) if sim(val,x)>=0.90]
        return []

    # ---- END-count replay (structural placement for END-bracketed blocks) ----
    # A code block whose nearest distinctive neighbours are END; lines can't be
    # forward-anchored by string matching (END; is non-distinctive boilerplate,
    # excluded as an anchor). Its real home is defined by the END; nesting it
    # sits inside. We recover that by counting END-class lines between the
    # before-anchor and the block in A, then replaying that count in B - a
    # structural signal that survives whitespace/indent differences (balanced
    # nesting is guaranteed by compilation).
    _ENDC=re.compile(r'^\s*END[;.]?\s*$', re.I)   # END / END; / END. (block closers)

    def _a_index_of_anchor(self, kind, val, block_start):
        """A index of the before-anchor: nearest line ABOVE block_start that
        produced (kind,val). None if not found within the local window."""
        if val is None: return None
        for j in range(block_start-1, max(-1, block_start-31), -1):
            line=self.A[j]
            if kind=='vtag':
                if self._vkey(line)==val: return j
            else:  # code / boundary: normalised similarity
                if sim(val, norm(line))>=0.90: return j
        return None

    def _end_count_between(self, a_idx, block_start):
        """Number of END-class lines in A strictly between a_idx and block_start
        (the inner-block closers the block sits below)."""
        return sum(1 for k in range(a_idx+1, block_start)
                   if self._ENDC.match(self.A[k]))

    def _walk_ends(self, pb, n, hi):
        """From B index pb, walk forward (skipping blanks) consuming exactly n
        END-class lines, not past hi (the enclosing proc's close). Return the
        index of the n-th END; (block anchors AFTER it). n==0 -> pb itself.
        None if n END-class lines aren't available within (pb, hi]."""
        if n==0: return pb
        seen=0; j=pb+1
        while j<=hi and j<len(self.B):
            s=self.B[j].strip()
            if s=='':
                j+=1; continue
            if self._ENDC.match(self.B[j]):
                seen+=1
                if seen==n: return j
                j+=1; continue
            # a non-blank, non-END line before consuming n ENDs: the structure
            # doesn't match (the block isn't simply END-bracketed here) -> bail.
            return None
        return None

    def _classify(self,inner,brace=False):
        # brace-style { Start..Stop } blocks are C/AL block comments: the ENTIRE inner content
        # is commented-out (suppressed) vendor code, regardless of per-line // markers.
        if brace:
            return 'VANILLA_SUPPRESS'   # block-commented vendor logic, no replacement -> always DEV
        real=[x for x in inner if norm(x) and not self.is_tag(x) and not CC.match(x)]
        commented=[x for x in inner if CC.match(x) and not self.is_tag(x)]
        if commented and not real: return 'VANILLA_SUPPRESS'   # commented vendor out, no replacement
        if commented and real:     return 'VANILLA_MOD'        # commented original + replacement
        return 'PURE_ADD'

    def score_block(self,b):
        content=self._classify(b['inner'],b.get('brace',False))
        vmod=(content=='VANILLA_MOD')
        bk,bv=self._anchor(b['start'],-1); ak,av=self._anchor(b['stop'],+1)
        bpos=self._locate(bk,bv); apos=self._locate(ak,av)
        # PROCEDURE-SCOPE CONFINEMENT: a CODE-section block belongs to exactly
        # one procedure in A; it must anchor inside the SAME-identity procedure
        # in B. Vendor boilerplate anchors (e.g. '// Start PA036544') recur
        # across procedures, so an unconfined search can bracket the block into
        # the wrong one. Resolve the enclosing A-procedure, match it in B (id
        # first, name fallback), and keep only anchor positions inside that B
        # span. A block enclosed in A by a procedure with NO B-match (vendor
        # removed/renamed-and-renumbered it) gets no valid anchor -> DEV.
        # Blocks OUTSIDE any procedure (global VAR / object trigger) are left
        # unconfined - their existing object-scope anchoring is unchanged.
        # END-replay after-anchor positions (block sits AFTER these END; lines,
        # not immediately after the before-anchor). Empty in the normal case.
        end_replay_pos=set()
        a_unit=self._a_enclosing(b['start'])
        if a_unit is not None:
            b_unit=self._b_match(a_unit)
            if b_unit is None:
                bpos=[]; apos=[]          # enclosing proc absent from B -> DEV
            else:
                lo,hi=b_unit['start'],b_unit['end']
                # The before-anchor must be strictly inside the proc body: a
                # block can't legitimately anchor backward onto a prior region.
                bpos=[p for p in bpos if lo<=p<=hi]
                # The after-anchor may reach one line PAST the proc's closing
                # END; - the boundary line that follows (the next PROCEDURE
                # header, or a blank then header). A block at the TAIL of a
                # procedure anchors forward onto that boundary; without this it
                # would lose its only after-anchor and false-gate to DEV. The
                # extension stops at the first following boundary, so it can't
                # reach into a sibling procedure's interior.
                hi_after=hi
                j=hi+1
                while j<len(self.B) and self.B[j].strip()=='':
                    j+=1
                if j<len(self.B) and BOUNDARY.match(self.B[j]):
                    hi_after=j
                apos=[p for p in apos if lo<=p<=hi_after]
                # TAIL / END-BRACKETED block: when a block's nearest distinctive
                # neighbours are END; lines (boilerplate, excluded as anchors),
                # _anchor's forward walk skips them and overshoots past the proc
                # onto the object trigger / changelog; confinement then strips
                # that -> apos empty -> false DEV. The block's TRUE forward home
                # is the END; line(s) it sits above. Recover it STRUCTURALLY (not
                # by indentation - operators' indent discipline varies): count
                # the END-class lines between the before-anchor and the block in
                # A, then replay that exact count forward from each matched
                # before-anchor in B. The block anchors after the last replayed
                # END;. Balanced END nesting is guaranteed (the object compiles),
                # so the count transfers even if whitespace doesn't. Scoped to
                # the confined, otherwise-anchorless case: cannot perturb any
                # block that already anchors, nor any unconfined object-scope
                # block (a_unit is None for those).
                if not apos and bpos:
                    # before-anchor's A index: the nearest distinctive line above
                    # the block that _anchor latched onto. Count END-class lines
                    # between it and the block, then replay forward in B.
                    a_bpos=self._a_index_of_anchor(bk,bv,b['start'])
                    if a_bpos is not None:
                        n_end=self._end_count_between(a_bpos, b['start'])
                        cand=[]
                        for pb in bpos:
                            tgt=self._walk_ends(pb, n_end, hi)
                            if tgt is not None:
                                cand.append(tgt)
                        if cand:
                            apos=cand
                            end_replay_pos=set(cand)
        # POSITION VALIDATION: after must follow before within a bounded window
        # in B. When the before-anchor occurs in B more than once (e.g. a vendor
        # tag reused several times), the FIRST valid pair is not necessarily the
        # right home for the block - it can anchor far too early. The block sits
        # immediately before its after-anchor, so prefer the TIGHTEST bracket:
        # the (pb,pa) pair with the smallest gap. Ties break on the later pb
        # (closest to pa).
        coherent=False; chosen=None
        block_span=(b['stop']-b['start'])+1
        window=block_span+15
        best=None
        for pb in bpos:
            cand=[pa for pa in apos if 0 < pa-pb <= window]
            if not cand: continue
            pa=min(cand); gap=pa-pb
            key=(gap, -pb)            # smaller gap wins; tie -> larger pb (nearer pa)
            if best is None or key<best[0]:
                best=(key,(pb,pa))
        if best is not None:
            coherent=True; chosen=best[1]
        type_w={'vtag':1.0,'boundary':0.75,'code':0.6,'none':0.0}
        score=(type_w[bk]+type_w[ak])/2 if coherent else 0.0
        PURE_T=0.75; VMOD_T=0.90
        # A chosen bracket that is TIGHT relative to the block size is an
        # unambiguous home even when the anchor strings recur elsewhere in B:
        # the tightest-bracket selection above already picked the closest valid
        # (before,after) pair, so a small gap means the block slots cleanly
        # between two real neighbours. Credit that so a clean tight code bracket
        # isn't rejected the way a loose/uncertain one would be. (Only lifts to
        # the PURE_ADD bar - VANILLA_MOD still needs its originals validated.)
        if coherent and chosen:
            gap=chosen[1]-chosen[0]
            if gap<=block_span+2:
                score=max(score, PURE_T)

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
        if content=='PURE_ADD':
            verdict='TRANSPLANT' if score>=PURE_T else 'DEV'
        elif content=='VANILLA_SUPPRESS':
            verdict='DEV'   # suppressing vendor logic is always a human decision
        else:  # VANILLA_MOD
            verdict='TRANSPLANT' if (score>=VMOD_T and orig_ok) else 'DEV'
        # INSERTION POINT for the executor. Normally a block sits immediately
        # after its before-anchor, so insert after chosen[0]. But an END-replay
        # block sits AFTER the END; line(s) it was bracketed against, so its
        # insert point is the after-anchor (chosen[1]) instead. Expose this
        # explicitly so the executor never re-derives it from chosen[0] alone.
        insert_after=None
        if coherent and chosen:
            insert_after = chosen[1] if chosen[1] in end_replay_pos else chosen[0]
        return dict(tag=f"{b['p']}{b['id']}",line=b['start']+1,content=content,
                    score=round(score,2),coherent=coherent,anchors=(bk,ak),orig_ok=orig_ok,verdict=verdict,
                    chosen=chosen,insert_after=insert_after)

import os as _os
_SAMPLES=_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),'samples')
def _s(fn): return _os.path.join(_SAMPLES, fn)
OBJS=[('T36',_s('Cust_T36.txt'),_s('20206Q1_T36.txt')),('C80',_s('Cust_C80.txt'),_s('20206Q1_C80.txt')),
      ('R790',_s('Cust_R790.txt'),_s('20206Q1_R790.txt')),('T14',_s('Cust_T14.txt'),_s('20206Q1_T14.txt')),
      ('T38',_s('Cust_T38.txt'),_s('20206Q1_T38.txt')),('T39',_s('Cust_T39.txt'),_s('20206Q1_T39.txt')),
      ('T5025400',_s('Cust_T5025400.txt'),_s('20206Q1_T5025400.txt'))]
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
