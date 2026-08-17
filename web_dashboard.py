from __future__ import annotations
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import metropia_v2 as v2

HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Metropia Manager</title><style>
:root{--red:#E63226;--black:#0A0A0A;--white:#fff;--muted:#666}*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--black);font-family:Inter,Arial,sans-serif}.top{padding:32px 5vw;border-bottom:1px solid #eee;display:flex;justify-content:space-between}.brand{font-weight:900;letter-spacing:-1px;font-size:28px}.brand i{color:var(--red);font-style:normal}.wrap{padding:40px 5vw;max-width:1300px;margin:auto}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card{border:1px solid #eee;padding:24px;min-height:130px}.label{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted)}.num{font-size:32px;font-weight:900;margin-top:14px}.section{margin-top:44px}.section h2{font-size:22px}.red{color:var(--red)}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:14px;border-bottom:1px solid #eee}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}}
</style></head><body><header class="top"><div class="brand">METROPIA <i>COFFEE</i></div><div>MANAGER / V2</div></header><main class="wrap"><div id="app">Loading…</div></main><script>
fetch('/api/dashboard').then(r=>r.json()).then(d=>{document.querySelector('#app').innerHTML=`<div class="grid">${[['Orders',d.orders],['Revenue',d.revenue.toLocaleString()+' soʻm'],['Open orders',d.open_orders],['Customers',d.customers]].map(x=>`<div class="card"><div class="label">${x[0]}</div><div class="num">${x[1]}</div></div>`).join('')}</div><div class="section"><h2>Top products</h2><table><tr><th>Product</th><th>Qty</th></tr>${d.top.map(x=>`<tr><td>${x[0]}</td><td>${x[1]}</td></tr>`).join('')}</table></div>`})
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/api/dashboard':
            d=v2.dashboard_stats(7); d['top']=v2.top_products(7); body=json.dumps(d,ensure_ascii=False).encode()
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers(); self.wfile.write(body); return
        body=HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass

def start_dashboard():
    if os.environ.get('METROPIA_DASHBOARD','1')!='1': return None
    port=int(os.environ.get('PORT','8080'))
    server=ThreadingHTTPServer(('0.0.0.0',port),Handler)
    import threading; threading.Thread(target=server.serve_forever,daemon=True).start(); return server
