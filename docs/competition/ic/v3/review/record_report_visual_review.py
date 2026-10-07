"""Seal the reviewer's actual inspection of the sixteen final r2 page PNGs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[5]
OWN=Path(__file__).resolve().parent

def guard(event,args):
    if event.startswith('socket.') or event=='subprocess.Popen':
        raise RuntimeError('This record is local-only and does not run other tools')
sys.addaudithook(guard)

def bind(path):
    raw=path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

validation_path=ROOT/'docs/competition/ic/v3/validation.json'
validation=json.loads(validation_path.read_text(encoding='utf-8'))
assert validation['attempt']=='r2'
expected={'docs/competition/ic/ICARUS_技术方案_v3.pdf':(10,'4bb214297d189ccbf446dd12e9bc848bffd216601c1c315241f6cb3bcc87f6a3'),
          'docs/competition/ic/ICARUS_佐证材料_v3.pdf':(6,'7fe5fe5aa78d654dc4e212cd25e2f2b202418d1d7a32d96ce755d8361a8e0dda')}
pages=[]
pdfs=[]
for document in validation['documents']:
    count,sha=expected[document['pdf']]
    original=bind(ROOT/document['pdf'])
    assert original['sha256']==sha==document['pdf_sha256']
    assert document['pages']==count
    pdfs.append(original)
    for page in document['page_records']:
        path=ROOT/page['png_path']
        actual=bind(path)
        assert actual['sha256']==page['png_sha256']
        assert page['page'] in range(1,count+1)
        pages.append({'pdf':document['pdf'],'page':page['page'],'page_png':actual,
                      'actually_viewed':True,'tool':'tools.view_image on each complete original r2 PNG, not only a thumbnail contact sheet',
                      'findings':'Readable text/tables and intact page numbering; no observed clipped glyphs, overlap or identity markings. Figure/table values and limitations were checked in their page context.'})
assert len(pages)==16
result={'schema':'icarus-v3-report-visual-review-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'reviewer':'AI machine reviewer, not a human H02','scope':'Final r2 technical PDF 10 pages and supporting PDF 6 pages, all individually inspected',
        'validation_binding':bind(validation_path),'pdfs':pdfs,'actual_pages_viewed':16,'pages':pages,
        'chart_review':{'path':'docs/competition/ic/v3/assets/new108_detection.png','actual_image_viewed':True,'baseline_zero':True,
                        'strategy_values':'12/10/8/8/11/10, each labelled N/12','descriptor':'4 distinct defects x 3 repetitions; no error bars or causal/significance claim'},
        'technical_page_1_architecture':'Roles and archive loop are legible; generic diagram is not described as a new UI screenshot or experiment output.',
        'scope_boundary':'Deck pages are not covered by this record and remain pending. This review does not establish human usability or native Office rendering.',
        'new_API_requests':0,'credentials_read':0,'new_DUT_runs':0,'new_source_tests':0,'new_PDF_renders':0,'reperformed_core_2192_checks':False}
path=OWN/'report_visual_review_r2.json'
with path.open('x',encoding='utf-8',newline='\n') as stream:
    json.dump(result,stream,ensure_ascii=False,indent=2)
    stream.write('\n')
print(json.dumps(bind(path),ensure_ascii=False))
