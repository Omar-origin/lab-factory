import concurrent.futures
import hashlib
import json
import urllib.request
import urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE='https://lab.elyther.top'
PUBLIC=ROOT/'mcp/lab-skill-factory/cloudflare/public'
checks=[('/',None),('/health',None),('/api/checkout/config',None),('/api/dashboard',None),('/docs','docs/index.html'),('/showcase','showcase/index.html'),('/plans','plans/index.html'),('/plans/plans.js','plans/plans.js'),('/assets/portal.css','assets/portal.css'),('/examples/native-report.docx','examples/native-report.docx'),('/examples/native-template.docx','examples/native-template.docx'),('/payment-assets/alipay.png','payment-assets/alipay.png')]
def check(pair):
 path,local=pair
 import subprocess
 response=subprocess.run(['curl','--silent','--show-error','--location','--max-time','30','--header','Cache-Control: no-cache','--write-out','\n%{http_code} %{url_effective}',BASE+path],capture_output=True,check=True)
 data,metadata=response.stdout.rsplit(b'\n',1)
 raw_status,url=metadata.decode().split(' ',1);status=int(raw_status)
 result={'path':path,'status':status,'final_url':url}
 if path=='/api/dashboard':result['ok']=status==401
 elif path=='/':result['ok']=status==200 and url.endswith('/showcase')
 elif path=='/health':result['ok']=status==200 and json.loads(data).get('ok') is True
 elif path=='/api/checkout/config':
  value=json.loads(data);result['ok']=status==200 and {p['id'] for p in value['plans']}=={'experience','permanent','team'}
 else:
  result['sha256']=hashlib.sha256(data).hexdigest();result['ok']=status==200 and data==(PUBLIC/local).read_bytes()
 return result
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(check,checks))
output={'ok':all(r['ok'] for r in results),'checks':results}
Path(__file__).with_name('live-checks.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(output,ensure_ascii=False,indent=2))
raise SystemExit(0 if output['ok'] else 1)
