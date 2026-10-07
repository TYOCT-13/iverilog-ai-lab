"""Check final v3 table projections, text limits and repository-relative citations."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import traceback

ROOT=Path(__file__).resolve().parents[5]
OWN=Path(__file__).resolve().parent
V3=OWN.parent
CHECKS=[]
ARTIFACTS={}

def guard(event,args):
    if event.startswith('socket.') or event=='subprocess.Popen':
        raise RuntimeError('No network or subprocess is permitted in this text audit')
sys.addaudithook(guard)

def bind(path):
    raw=path.read_bytes()
    item={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    ARTIFACTS[item['path']]=item
    return item

def read_text(path):
    bind(path)
    return path.read_text(encoding='utf-8')

def save(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')

def unit(name,callback,*args):
    assert name not in {item['id'] for item in CHECKS}
    try:
        detail=callback(*args)
    except Exception as exc:
        CHECKS.append({'id':name,'status':'failed','error':str(exc),'traceback':traceback.format_exc()})
        return None
    CHECKS.append({'id':name,'status':'passed','detail':detail})
    return detail

def equal(actual,expected):
    assert actual==expected,{'actual':actual,'expected':expected}
    return {'actual':actual,'expected':expected}

def tables(content):
    blocks=[]
    block=[]
    for line in content.splitlines()+['']:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            block.append([part.strip() for part in line.strip()[1:-1].split('|')])
        elif block:
            if len(block)>1 and all(re.fullmatch(r':?-+:?',part) for part in block[1]):
                blocks.append({'header':block[0],'rows':block[2:]})
            block=[]
    return blocks

def find(content,header):
    matches=[table for table in tables(content) if table['header']==header]
    assert len(matches)==1,(header,len(matches))
    return matches[0]['rows']

def expected_rows(rows,with_repeat,with_tokens):
    result=[]
    for row in rows:
        cells=[row['label'],str(row['detected_samples'])]
        if with_repeat:cells.append('/'.join(str(number) for number in row['repeat_detections']))
        cells.append(str(row['requests']))
        if with_tokens:cells.append(str(row['usage']['total_tokens']))
        result.append(cells)
    return result

def links(content,path):
    references=[]
    for label,target in re.findall(r'!?\[([^\]]*)\]\(([^)]+)\)',content):
        if re.match(r'https?://',target):
            references.append({'label':label,'target':target,'scope':'external URL recorded; no network check in this audit'})
            continue
        if target.startswith('#'):continue
        target_path=(path.parent/target.split('#',1)[0]).resolve()
        assert target_path.is_relative_to(ROOT),('citation outside repository',target)
        assert target_path.is_file(),('missing local cited file',target)
        references.append({'label':label,'target':target,'artifact':bind(target_path)})
    return references

def section_text(content,title):
    match=re.search(r'^## '+re.escape(title)+r'\s*\n(.*?)(?=^## |\Z)',content,re.M|re.S)
    assert match,title
    return match[1].strip()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--attempt',required=True)
    parser.add_argument('--final-text-authorized',required=True,action='store_true')
    args=parser.parse_args()
    assert re.fullmatch(r'text-r[1-9][0-9]*',args.attempt)
    attempt=OWN/args.attempt
    attempt.mkdir(exist_ok=False)
    data=json.loads(read_text(V3/'material_data.json'))
    documents={name:read_text(V3/(name+'.md')) for name in ['technical_report','supporting_evidence','README','submission_copy']}
    new=data['latest_new108']['strategies']
    old=data['historical_v8_432']['strategies']
    specs=[('technical_new',documents['technical_report'],['策略','检出/12','三次检出各/4','API请求'],expected_rows(new,True,False)),
           ('technical_old',documents['technical_report'],['策略','历史检出/48','API请求','输入加输出tokens'],expected_rows(old,False,True)),
           ('supporting_new',documents['supporting_evidence'],['策略','检出/12','各重复/4','API请求','tokens'],expected_rows(new,True,True)),
           ('supporting_old',documents['supporting_evidence'],['策略','历史检出/48','各重复/16','请求','tokens'],expected_rows(old,True,True))]
    for name,content,header,expected in specs:
        actual=unit('table_identity/'+name,find,content,header)
        if actual is not None:
            unit('table_row_count/'+name,equal,len(actual),len(expected))
            for number,(actual_row,expected_row) in enumerate(zip(actual,expected),1):
                unit('table_row/'+name+'/'+str(number),equal,actual_row,expected_row)
    title=section_text(documents['submission_copy'],'作品名称')
    intro=section_text(documents['submission_copy'],'项目简介')
    unit('submission_name_matches_material_data',equal,title,data['project_name'])
    unit('submission_name_length',lambda:equal(len(title)<=data['rules']['name_max_chinese_characters'],True))
    unit('submission_intro_length',lambda:equal(len(intro)<=data['rules']['intro_max_characters'],True))
    unit('seven_section_outline',equal,re.findall(r'^## [一二三四五六七]、(.+)$',documents['technical_report'],re.M),data['rules']['seven_sections'])
    unit('six_supporting_sections',equal,[number for number in re.findall(r'^## V(3[1-6])\s',documents['supporting_evidence'],re.M)],['31','32','33','34','35','36'])
    unit('README_correct_machine_vs_human_originals',lambda:equal('后两者没有真实原件' in documents['README'],False))
    citations={}
    for name,content in documents.items():
        citations[name]=unit('local_citation_targets/'+name,links,content,V3/(name+'.md'))
    inputs=list(ARTIFACTS.values())
    for item in inputs:
        unit('unchanged/'+item['path'],equal,bind(ROOT/item['path']),item)
    failures=[item for item in CHECKS if item['status']=='failed']
    result={'schema':'icarus-v3-text-table-review-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'unique_text_check_units':len(CHECKS),'passed_check_units':len(CHECKS)-len(failures),'failed_check_units':len(failures),
            'checks':CHECKS,'citations':citations,'artifacts':list(ARTIFACTS.values()),
            'submission_counts':{'name_unicode_characters':len(title),'intro_unicode_characters':len(intro),'count_method':'all Unicode characters, including punctuation and Latin letters; plain text only'},
            'scope':'Four complete six-strategy tables are compared row-by-row against sealed material facts; all local Markdown citations must exist. Prose meaning and external URL reachability are separate.',
            'new_API_requests':0,'credentials_read':0,'new_DUT_runs':0,'new_source_tests':0,'external_url_requests':0,'H02_human_review':False}
    save(attempt/'result.json',result)
    log={'units':len(CHECKS),'passed':len(CHECKS)-len(failures),'failed':failures,'result':bind(attempt/'result.json')}
    save(attempt/'log.json',log)
    save(attempt/'receipt.json',{'schema':'icarus-v3-text-review-attempt-v1','tool':bind(Path(__file__).resolve()),'result':bind(attempt/'result.json'),'log':bind(attempt/'log.json')})
    print(json.dumps(log,ensure_ascii=False))
    return 0 if not failures else 1

if __name__=='__main__':raise SystemExit(main())
