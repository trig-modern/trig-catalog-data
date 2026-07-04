import json, re
d=json.load(open('picked_156.json'))
PRE='https://dd3ka9h4chfr8.cloudfront.net/image/725136000567/image_'
MID='/-S1200x1200-FJPG/'
bare=re.compile(r'^[A-Za-z]{2,4}_\d{1,2}$')
def full(sku, tok):
    h,suf=tok.split('|',1)
    if bare.match(suf):
        fname=sku+'_'+suf
    else:
        fname=suf  # already a full filename stem
    if not fname.lower().endswith(('.jpg','.png')): fname+='.jpg'
    return PRE+h+MID+fname
out=[]
for r in d:
    seen=set(); urls=[]
    for tok in r['im']:
        u=full(r['s'],tok)
        if u in seen: continue
        seen.add(u); urls.append(u)
    out.append({'sku':r['s'],'name':r['n'],'chip':r['c'],'images':urls[:4]})
json.dump(out, open('fh_urls.json','w'), indent=0)
# dump flat url list for verification
allurls=[]
for r in out:
    for u in r['images']: allurls.append(u)
open('fh_all_urls.txt','w').write('\n'.join(allurls))
print('records:',len(out),'total urls:',len(allurls),'unique:',len(set(allurls)))
