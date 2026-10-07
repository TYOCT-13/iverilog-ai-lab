"""Inspect final v3 material artifacts, without editing or re-exporting them."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import traceback
import posixpath
import xml.etree.ElementTree as ET
import zipfile
import fitz

ROOT=Path(__file__).resolve().parents[5]
OWN=Path(__file__).resolve().parent
V3=OWN.parent
CHECKS=[]
ARTIFACTS={}

def guard(event,args):
    if event.startswith('socket.') or event=='subprocess.Popen':
        raise RuntimeError('This audit forbids network and child-process execution')
sys.addaudithook(guard)

def bind(path):
    raw=path.read_bytes()
    item={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    ARTIFACTS[item['path']]=item
    return item

def read(path):
    bind(path)
    return json.loads(path.read_text(encoding='utf-8'))

def text(path):
    bind(path)
    return path.read_text(encoding='utf-8')

def save(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')

def unit(name,callback,*args):
    assert name not in {item['id'] for item in CHECKS}
    try:
        value=callback(*args)
    except Exception as exc:
        CHECKS.append({'id':name,'status':'failed','error_type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc()})
        return None
    CHECKS.append({'id':name,'status':'passed'})
    return value

def equal(actual,expected,label):
    assert actual==expected,label
    return True

def official_rules(material):
    receipt=read(V3/'rules_validation.json')
    results=[]
    for source in receipt['sources']:
        path=ROOT/source['path']
        actual=bind(path)
        assert actual['sha256']==source['sha256'] and actual['bytes']==source['bytes']
        assert source['http_status']==200 and source['retrieval']=='saved'
        with fitz.open(path) as document:
            assert len(document)==source['pages']
            content='\n'.join(page.get_text('text') for page in document)
        normalized=re.sub(r'\s+','',content)
        results.append({'source':actual,'url':source['url'],'pages':source['pages'],'text':content})
        if path.name=='ic_rules.pdf':
            for phrase in ['不超过20字','不超过300字','不得超过10M','演示视频（若有）','MP4','3-5分钟','300MB以内','合并为一个PDF','均不得出现参赛团队所在学校名称','指导教师信息']:
                assert phrase in normalized,('official rule phrase missing',phrase)
            assert material['rules']['technical_pdf_max_megabytes']==10
            assert material['rules']['video']['optional'] is True
            assert material['rules']['defense_delivery_format']=='PDF'
            assert material['rules']['supporting_evidence_delivery']=='one_consolidated_PDF'
            assert material['rules']['scoring']=={'needs':30,'innovation':30,'effect':30,'summary':10}
        else:
            for phrase in ['没有经济效益可以不写','不影响作品成绩','自己在学习、科研工作中','一、作品概述','二、需求分析','三、AI技术工具选择与运用','四、项目实施','五、应用成效','六、总结与展望','七、附录']:
                assert phrase in normalized,('official outline phrase missing',phrase)
    return {'receipt':bind(V3/'rules_validation.json'),'sources':results,
            'interpretation':'Manually reviewed full extracted rules/outline: optional video; user feedback may be supporting evidence, not compulsory human H01/H02. Learning/research needs are permitted; economic benefits may be omitted.',
            'deadline_basis':'2026-10-15 20:00 from root 2026-10-05 read of official notice/4756; deadline is not stated in these two original PDFs.',
            'current_audit_network_requests':0}

def chart_facts(material):
    source=read(V3/'assets/chart_source.json')
    expected=material['latest_new108']['strategies']
    assert source['data_sha256']==bind(V3/'material_data.json')['sha256']
    assert source['chart_sha256']==bind(ROOT/source['chart'])['sha256']
    assert source['strategy_ids']==[row['id'] for row in expected]
    assert source['values']==[row['detected_samples'] for row in expected]
    assert source['denominator_per_strategy']==material['latest_new108']['defect_tasks_per_strategy']
    assert source['distinct_defects']==4 and source['repeats']==3
    assert source['error_bars'].startswith('not used')
    return source

def source_document(path):
    value=text(path)
    suspect=[]
    for number,line in enumerate(value.splitlines(),1):
        if re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK|独立外部盲测|预训练未见|完成.*H02|真人.*强制|人审.*强制|训练了模型|工业泛化|显著优于|经济收益',line):
            suspect.append({'line':number,'text':line})
    return {'artifact':bind(path),'characters':len(value),'headings':[line for line in value.splitlines() if line.startswith('#')],
            'claims_for_context_review':suspect,'text':value,
            'candidate_lines_are_not_automatic_failures':True}

def pdf(path,attempt,role,limit=None):
    original=bind(path)
    if limit is not None:assert original['bytes']<=limit,'technical PDF exceeds conservative decimal 10 MB'
    directory=attempt/(role+'-render')
    directory.mkdir(exist_ok=False)
    pages,extracted=[],[]
    with fitz.open(path) as document:
        assert not document.is_encrypted
        metadata=document.metadata
        assert not re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK',json.dumps(metadata,ensure_ascii=False)), 'identity in PDF metadata'
        assert document.embfile_count()==0,'embedded attachments need separate review'
        assert len(document)>0
        for index,page in enumerate(document,1):
            content=page.get_text('text')
            extracted.append(content)
            if role != 'defense':
                assert content.strip(),('no selectable text',role,index)
            elif not content.strip():
                assert page.get_images(full=True),('neither text nor slide image',role,index)
            assert not re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK',content),('local identity path in PDF text',role,index)
            spans,overflow,fonts=[],[],[]
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    for span in line.get('spans',[]):
                        if not span['text'].strip():continue
                        box=fitz.Rect(span['bbox'])
                        if not page.rect.contains(box):overflow.append({'text':span['text'],'bbox':list(box)})
                        spans.append({'text':span['text'],'bbox':list(box),'font':span['font'],'size':span['size']})
            assert not overflow,('text outside page',role,index,overflow[:5])
            for font in page.get_fonts(full=True):
                raw_font=document.extract_font(font[0])
                fonts.append({'name':font[3],'type':font[2],'embedded':bool(raw_font[3])})
            image=directory/f'page-{index:02d}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.6,1.6),alpha=False).save(image)
            save(directory/f'page-{index:02d}-layout.json',spans)
            pages.append({'page':index,'size_points':list(page.rect),'text_characters':len(content),
                          'png':bind(image),'fonts':fonts,'outside_page_text':overflow,'text':content})
        count=len(document)
    save(attempt/(role+'-text.json'),extracted)
    assert bind(path)==original,('PDF changed during read',role)
    return {'artifact':original,'role':role,'pages':count,'metadata':metadata,'page_records':pages,
            'readable_selectable_text':all(bool(value.strip()) for value in extracted),
            'raster_slide_pdf':role=='defense' and not any(value.strip() for value in extracted),
            'visual_acceptance':'pending explicit reviewer image inspection',
            'render_backend':'PyMuPDF read-only page render; does not re-export original PDF'}

def pptx(path,attempt):
    original=bind(path)
    ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main',
        'c':'http://schemas.openxmlformats.org/drawingml/2006/chart','dc':'http://purl.org/dc/elements/1.1/',
        'cp':'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'}
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        assert len(names)==len(set(names))==len({name.casefold() for name in names})
        assert archive.testzip() is None
        for info in archive.infolist():
            parsed=PurePosixPath(info.filename)
            assert not parsed.is_absolute() and '..' not in parsed.parts and ':' not in info.filename and '\\' not in info.filename
            assert not stat.S_ISLNK(info.external_attr>>16)
        properties=ET.fromstring(archive.read('docProps/core.xml'))
        fields={node.tag.split('}',1)[-1]:node.text for node in properties}
        assert not re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK',json.dumps(fields,ensure_ascii=False)), 'identity in PPTX core properties'
        presentation=ET.fromstring(archive.read('ppt/presentation.xml'))
        size=presentation.find('p:sldSz',ns)
        page_count=len(presentation.findall('p:sldIdLst/p:sldId',ns))
        slide_files=sorted([name for name in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',name)],key=lambda name:int(re.search(r'(\d+)\.xml',name)[1]))
        assert len(slide_files)==page_count
        slides=[]
        for number,name in enumerate(slide_files,1):
            root=ET.fromstring(archive.read(name))
            values=[node.text or '' for node in root.findall('.//a:t',ns)]
            content='\n'.join(values)
            assert not re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK',content),('local identity in PPTX text',number)
            tables=[]
            for table in root.findall('.//a:tbl',ns):
                rows=[]
                for row in table.findall('a:tr',ns):
                    rows.append([''.join(node.text or '' for node in cell.findall('.//a:t',ns)) for cell in row.findall('a:tc',ns)])
                tables.append(rows)
            slides.append({'slide':number,'xml':name,'text':content,'text_runs':len(values),'native_tables':tables,
                           'native_chart_references':len(root.findall('.//c:chart',ns)),
                           'native_shapes':len(root.findall('.//p:sp',ns)),
                           'picture_shapes':len(root.findall('.//p:pic',ns))})
        charts=[]
        for name in sorted(n for n in names if re.fullmatch(r'ppt/(?:slides/)?charts/chart\d+\.xml',n)):
            root=ET.fromstring(archive.read(name))
            series=[]
            for item in root.findall('.//c:ser',ns):
                series.append({'labels':[v.text for v in item.findall('.//c:strCache/c:pt/c:v',ns)],
                               'values':[v.text for v in item.findall('.//c:val//c:numCache/c:pt/c:v',ns)]})
            relationship_path=str(PurePosixPath(name).parent/'_rels'/(PurePosixPath(name).name+'.rels'))
            relationships=[]
            if relationship_path in names:
                for relation in ET.fromstring(archive.read(relationship_path)):
                    target=relation.attrib['Target']
                    assert relation.attrib.get('TargetMode')!='External','external chart workbook link'
                    resolved=posixpath.normpath(str(PurePosixPath(name).parent/target))
                    assert resolved in names,('missing chart relationship target',resolved)
                    relationships.append({'id':relation.attrib['Id'],'target':target,'resolved_path':resolved})
            charts.append({'path':name,'series':series,'relationships':relationships,
                           'error_bars':len(root.findall('.//c:errBars',ns)),
                           'value_axis_min':[node.attrib['val'] for node in root.findall('.//c:valAx/c:scaling/c:min',ns)],
                           'value_axis_max':[node.attrib['val'] for node in root.findall('.//c:valAx/c:scaling/c:max',ns)]})
        notes=[]
        for name in sorted(n for n in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)):
            root=ET.fromstring(archive.read(name))
            note_text='\n'.join(node.text or '' for node in root.findall('.//a:t',ns))
            assert not re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK',note_text),('local identity in PPTX notes',name)
            notes.append({'path':name,'text':note_text})
        workbooks=[]
        import io
        workbook_ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        for name in sorted(n for n in names if n.startswith('ppt/embeddings/') and n.endswith('.xlsx')):
            raw=archive.read(name)
            with zipfile.ZipFile(io.BytesIO(raw)) as workbook:
                assert workbook.testzip() is None
                workbook_metadata={}
                for metadata_name in ['docProps/core.xml','docProps/custom.xml']:
                    if metadata_name in workbook.namelist():
                        metadata_root=ET.fromstring(workbook.read(metadata_name))
                        workbook_metadata[metadata_name]={node.tag.split('}',1)[-1]:node.text for node in metadata_root}
                assert not re.search(r'TYOCT|C:\\Users|D:\\Users|E:\\FPGA_WORK',json.dumps(workbook_metadata,ensure_ascii=False)),'local identity in embedded workbook metadata'
                strings=[]
                if 'xl/sharedStrings.xml' in workbook.namelist():
                    root=ET.fromstring(workbook.read('xl/sharedStrings.xml'))
                    strings=[''.join(node.text or '' for node in item.findall('.//s:t',workbook_ns)) for item in root.findall('s:si',workbook_ns)]
                sheets=[]
                for sheet_name in sorted(n for n in workbook.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n)):
                    sheet=ET.fromstring(workbook.read(sheet_name))
                    cells=[]
                    for cell in sheet.findall('.//s:c',workbook_ns):
                        node=cell.find('s:v',workbook_ns)
                        value=None if node is None else node.text
                        if cell.attrib.get('t')=='s' and value is not None:
                            value=strings[int(value)]
                        elif cell.attrib.get('t')=='inlineStr':
                            value=''.join(node.text or '' for node in cell.findall('.//s:t',workbook_ns))
                        formula=cell.find('s:f',workbook_ns)
                        cells.append({'reference':cell.attrib.get('r'),'type':cell.attrib.get('t'),'value':value,'formula':None if formula is None else formula.text})
                    sheets.append({'path':sheet_name,'cells':cells})
                workbooks.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'crc_passed':True,'metadata':workbook_metadata,'sheets':sheets})
        members=[{'path':info.filename,'bytes':info.file_size,'sha256':hashlib.sha256(archive.read(info.filename)).hexdigest(),'crc32':f'{info.CRC:08x}'} for info in archive.infolist()]
        result={'artifact':original,'zip_members':len(names),'crc_all_members_passed':True,'pages':page_count,
                'slide_size':dict(size.attrib),'metadata':fields,'slides':slides,'charts':charts,'notes':notes,'embedded_workbooks':workbooks,'members':members,
                'native_table_owner_slides':[slide['slide'] for slide in slides if slide['native_tables']],
                'native_chart_owner_slides':[slide['slide'] for slide in slides if slide['native_chart_references']],
                'native_Office_rendering_verified':False,'boundary':'Read-only OOXML content/metadata/CRC inspection; no PowerPoint opening, re-export or platform-font layout proof.'}
    save(attempt/'pptx-extraction.json',result)
    assert bind(path)==original
    return result

def presentation_facts(presentation,material):
    assert presentation['pages']==12
    assert presentation['native_table_owner_slides']==[4,5,7,8,9,10,12]
    assert presentation['native_chart_owner_slides']==[6,11]
    assert len(presentation['charts'])==len(presentation['embedded_workbooks'])==3
    assert presentation['metadata']=={},'PPTX core properties should be empty for anonymous delivery'
    assert all(slide['picture_shapes']==0 for slide in presentation['slides']),'unexpected raster picture in editable deck'
    workbooks={item['path']:item for item in presentation['embedded_workbooks']}
    chart_records=[]
    for chart in presentation['charts']:
        assert len(chart['series'])==1
        series=chart['series'][0]
        assert len(series['labels'])==len(series['values'])
        pairs=[(label,float(value)) for label,value in zip(series['labels'],series['values'])]
        assert chart['error_bars']==0
        assert chart['value_axis_min']==['0']
        linked=[item['resolved_path'] for item in chart['relationships'] if item['resolved_path'].endswith('.xlsx')]
        assert len(linked)==1
        workbook=workbooks[linked[0]]
        assert len(workbook['sheets'])==1
        cells={item['reference']:item for item in workbook['sheets'][0]['cells']}
        assert all(item['formula'] is None for item in cells.values()),'embedded chart data contains formulas rather than literals'
        workbook_pairs=[(cells['A'+str(index)]['value'],float(cells['B'+str(index)]['value'])) for index in range(2,len(pairs)+2)]
        assert pairs==workbook_pairs,('cached chart values differ from embedded literal workbook',chart['path'])
        if len(pairs)==6:
            expected={row['label']:float(row['detected_samples']) for row in material['latest_new108']['strategies']}
            assert dict(pairs)==expected,'new108 native chart differs from facts'
            assert chart['value_axis_max']==['12']
            kind='new108: each strategy denominator 12 = 4 distinct defects x 3 repeats'
        elif chart['path'].endswith('chart2.xml'):
            fifo=material['historical_support']['fifo']
            assert dict(pairs)=={'修复前':float(fifo['before_differences']),'修复后':float(fifo['after_differences'])}
            kind='manual FIFO specification repair: raw differences; not Agent gain'
        else:
            external=material['historical_support']['external']
            assert dict(pairs)=={'旧人工规格':float(external['before_detected']),'补全计时后':float(external['after_detected'])}
            kind='manual external finite specification repair: 15 artificial variants; not Agent gain'
        chart_records.append({'chart':chart['path'],'pairs':pairs,'workbook':workbook['path'],'kind':kind})
    return {'charts_and_literals':chart_records,'native_table_slides':presentation['native_table_owner_slides'],
            'all_cache_and_workbook_values_match':True,'native_structure_found':True,'native_Office_verified':False}

def defense_images(path,render_dir):
    import io
    from PIL import Image,ImageChops
    original=bind(path)
    records=[]
    with fitz.open(path) as document:
        for number,page in enumerate(document,1):
            images=page.get_images(full=True)
            assert len(images)==1,('expected one complete slide image per PDF page',number,len(images))
            raw=document.extract_image(images[0][0])['image']
            source_path=render_dir/f'slide-{number:02d}.png'
            source_binding=bind(source_path)
            with Image.open(source_path) as source,Image.open(io.BytesIO(raw)) as embedded:
                left,right=source.convert('RGB'),embedded.convert('RGB')
                assert left.size==right.size==(2560,1440)
                difference=ImageChops.difference(left,right)
                assert difference.getbbox() is None,('PDF embedded slide differs from full native-deck rendered PNG',number)
                records.append({'page':number,'native_deck_render_png':source_binding,'PDF_embedded_image_pixel_identical':True,'size_pixels':list(left.size)})
    assert bind(path)==original
    return {'PDF':original,'pages':len(records),'records':records,'method':'read-only extraction of embedded PDF image; RGB pixel comparison with the actually inspected complete native-deck render, no PDF re-export'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--attempt',required=True)
    parser.add_argument('--final-materials-authorized',required=True,action='store_true')
    parser.add_argument('--defense-pdf',required=True)
    parser.add_argument('--defense-pptx',required=True)
    parser.add_argument('--defense-render-dir',required=True)
    args=parser.parse_args()
    assert re.fullmatch(r'outputs-r[1-9][0-9]*',args.attempt)
    attempt=OWN/args.attempt
    attempt.mkdir(exist_ok=False)
    data=read(V3/'material_data.json')
    current_sources={name:bind(ROOT/item['path']) for name,item in data['sources'].items()}
    for name,item in data['sources'].items():unit('sealed_source/'+name,equal,current_sources[name],item,'source binding differs from material data')
    rules=unit('official_original_rules_and_outline',official_rules,data)
    chart=unit('new108_chart_data_and_png_binding',chart_facts,data)
    sources={}
    for stem in ['technical_report','supporting_evidence','README','submission_copy']:
        sources[stem]=unit('source/'+stem,source_document,V3/(stem+'.md'))
    for stem in ['speaker_notes','qa_questions','README']:
        sources['defense_'+stem]=unit('source/defense_'+stem,source_document,ROOT/'docs/competition/ic/defense_v3'/(stem+'.md'))
    defense_data=unit('defense_authoring_material_data_binding',read,ROOT/'docs/competition/ic/defense_v3/data.json')
    if defense_data:
        unit('defense_authoring_data_sha',equal,defense_data['material_source_sha256'],bind(V3/'material_data.json')['sha256'],'defense authoring source differs from factual data')
    defense_summary=read(ROOT/'docs/competition/ic/defense_v3/finalization_summary.json')
    defense_sources=read(ROOT/'docs/competition/ic/defense_v3/source_checksums.json')
    for item in defense_sources['items']:
        actual=bind(ROOT/item['relative_path'])
        unit('defense_source_sha/'+item['relative_path'],equal,actual['sha256'],item['sha256'],'defense source differs from published build snapshot')
        unit('defense_source_bytes/'+item['relative_path'],equal,actual['bytes'],item['size_bytes'],'defense source size differs from published build snapshot')
    for item in list(defense_summary['artifacts'].values())+[defense_summary['finalization_receipt'],defense_summary['QA_report'],defense_summary['source_checksums']]:
        actual=bind(ROOT/item['path'])
        unit('defense_public_receipt_sha/'+item['path'],equal,actual['sha256'],item['sha256'],'formal defense artifact differs from published summary')
    documents={}
    paths={'technical_report':ROOT/'docs/competition/ic/ICARUS_技术方案_v3.pdf',
           'supporting_evidence':ROOT/'docs/competition/ic/ICARUS_佐证材料_v3.pdf',
           'defense':ROOT/args.defense_pdf}
    for role,path in paths.items():
        documents[role]=unit('pdf/'+role,pdf,path,attempt,role,10_000_000 if role=='technical_report' else None)
    presentation=unit('pptx/structure_metadata_and_text',pptx,ROOT/args.defense_pptx,attempt)
    if presentation:
        presentation_fact_check=unit('pptx/native_tables_charts_and_literal_workbooks_facts',presentation_facts,presentation,data)
    else:
        presentation_fact_check=None
    if presentation and documents['defense']:
        unit('defense_pdf_vs_pptx_page_count',equal,presentation['pages'],documents['defense']['pages'],'PDF and PPTX page counts differ')
        defense_image_check=unit('defense_pdf_pixels_vs_native_deck_render',defense_images,ROOT/args.defense_pdf,ROOT/args.defense_render_dir)
    else:
        defense_image_check=None
    validation=read(V3/'validation.json')
    unit('PDF_build_material_data_binding',equal,validation['material_data']['sha256'],bind(V3/'material_data.json')['sha256'],'PDF builder used a different material data snapshot')
    for doc in validation['documents']:
        unit('build_source_sha/'+doc['source'],equal,bind(ROOT/doc['source'])['sha256'],doc['source_sha256'],'source changed since PDF export')
        unit('build_pdf_sha/'+doc['pdf'],equal,bind(ROOT/doc['pdf'])['sha256'],doc['pdf_sha256'],'PDF changed since builder validation')
    input_artifacts=[item for item in ARTIFACTS.values() if not item['path'].startswith(attempt.relative_to(ROOT).as_posix()+'/')]
    for item in input_artifacts:
        unit('artifact_unchanged/'+item['path'],equal,bind(ROOT/item['path']),item,'input artifact changed during read-only inspection')
    failed=[item for item in CHECKS if item['status']=='failed']
    result={'schema':'ic-v3-final-materials-mechanical-review-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'mechanical_checks_passed':not failed,'unique_material_output_check_units':len(CHECKS),'failed_check_units':len(failed),
            'scope':'Final Markdown/PDF/PPTX facts and metadata candidates, chart bindings, original rules and read-only page rendering. Context/visual reviewer acceptance is separate.',
            'reviewer':'AI machine reviewer, not formal independent human H02','checks':CHECKS,'rules':rules,'chart':chart,'sources':sources,
            'documents':documents,'presentation':presentation,'presentation_fact_check':presentation_fact_check,'defense_image_check':defense_image_check,'artifacts':list(ARTIFACTS.values()),
            'new_API_requests':0,'credentials_read':0,'new_DUT_runs':0,'new_source_tests':0,'reperformed_core_2192_checks':False,
            'native_Office_verified':False,'visual_review_complete':False,'final_claim_review_complete':False}
    result['new_read_only_PDF_page_renders']=sum(doc['pages'] for doc in documents.values() if doc)
    save(attempt/'result.json',result)
    log={'mechanical_checks_passed':result['mechanical_checks_passed'],'units':len(CHECKS),'failed':failed,'result':bind(attempt/'result.json')}
    save(attempt/'log.json',log)
    save(attempt/'receipt.json',{'schema':'ic-v3-output-audit-attempt-v1','result':bind(attempt/'result.json'),'log':bind(attempt/'log.json'),
                             'tool':bind(Path(__file__).resolve()),'new_API_requests':0,'credentials_read':0,'new_DUT_runs':0})
    print(json.dumps(log,ensure_ascii=False))
    return 0 if not failed else 1

if __name__=='__main__':raise SystemExit(main())
