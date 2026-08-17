import ast,re,sys
src=open('texts.py',encoding='utf-8').read(); tree=ast.parse(src)
texts=None
for n in tree.body:
    if isinstance(n,ast.Assign):
        if any(isinstance(t,ast.Name) and t.id=='TEXTS' for t in n.targets):
            texts=ast.literal_eval(n.value); break
if texts is None:
    print('TEXTS dictionary not found; manual review required.'); sys.exit(2)
bad=[]
for k,v in texts.get('uz',{}).items():
    if re.search(r'[А-Яа-яЁёҚқҒғҲҳЎўҚқ]',str(v)):
        bad.append((k,v))
print('UZBEK LATIN CHECK')
if bad:
    for k,v in bad: print(f'- {k}: {v}')
    sys.exit(1)
print('PASS — no Cyrillic characters found in TEXTS["uz"].')
