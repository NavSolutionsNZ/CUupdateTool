import sys; sys.path.insert(0,'/home/claude')
from scorer import Scorer, OBJS, CUST, ALL

# expected verdicts (TRANSPLANT or DEV) keyed by (obj, tag@line)
EXP = {
 ('T36','AP2263@5221'):'TRANSPLANT',
 ('T36','AP001691@2995'):'DEV', ('T36','AP001691@3005'):'DEV', ('T36','AP001651@7766'):'DEV',
 ('C80','AP2308@119'):'DEV', ('C80','WBL10@115'):'DEV',
 ('R790','AP002098@696'):'DEV',        # SUPPRESS
 ('R790','AP002098@725'):'TRANSPLANT', # pure add
 ('T14','AP001651@606'):'TRANSPLANT', ('T14','WBL@876'):'TRANSPLANT',
 ('T39','WBL-006@3523'):'DEV',  # SUPPRESS (was wrongly TRANSPLANT before)
 ('T39','WBL-006@3540'):'DEV',  # SUPPRESS
 ('T39','WBL-009@31'):'TRANSPLANT',
 ('T39','WBL-006@761'):'DEV',   # VANILLA_MOD
 ('T5025400','WBL-006@83'):'TRANSPLANT',
 # T38 VANILLA_MOD -> DEV
 ('T38','WBL-009@688'):'DEV', ('T38','WBL-009@719'):'DEV', ('T38','WBL-009@1455'):'DEV', ('T38','WBL-009@2735'):'DEV',
}

results={}
for name,a,b in OBJS:
    s=Scorer(a,b,CUST,ALL)
    for blk in s.blocks():
        r=s.score_block(blk)
        results[(name,f"{r['tag']}@{r['line']}")]=r

passed=failed=unknown=0
print(f"{'case':28} {'expected':11} {'got':11} {'result'}")
for name,a,b in OBJS:
    s=Scorer(a,b,CUST,ALL)
    for blk in s.blocks():
        r=s.score_block(blk)
        key=(name,f"{r['tag']}@{r['line']}")
        got=r['verdict']
        if key in EXP:
            ok = (got==EXP[key])
            print(f"{key[0]+' '+key[1]:28} {EXP[key]:11} {got+' ('+r['content'][:4]+')':16} {'PASS' if ok else 'FAIL <<<'}")
            passed+=ok; failed+=(not ok)
        else:
            unknown+=1
print(f"\nPASS={passed} FAIL={failed} (untested blocks={unknown})")
