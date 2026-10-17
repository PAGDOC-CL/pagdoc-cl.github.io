"""Bounded offline document extraction and raster previews; no external services."""
import csv
import io
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
from datetime import datetime,timedelta
import xml.etree.ElementTree as ET
import zipfile
from storage import validate_office

MAX_TEXT=100_000
MAX_PAGES=24


class ExtractionError(ValueError):pass


def command(args,directory,timeout=35):
    limiter=shutil.which('prlimit')
    if not limiter:raise ExtractionError('El motor privado no está instalado.')
    env={'PATH':'/usr/local/bin:/usr/bin:/bin','LC_ALL':'C','HOME':str(directory),'TMPDIR':str(directory),'OMP_THREAD_LIMIT':'1'}
    try:
        subprocess.run([limiter,'--as=536870912','--cpu=30','--fsize=33554432','--',*map(str,args)],cwd=directory,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=timeout,check=True,env=env)
    except (OSError,subprocess.SubprocessError) as exc:raise ExtractionError('No se completó la lectura dentro de los límites.') from exc


def bounded_text(path):
    if path.stat().st_size>2_000_000:raise ExtractionError('El texto excede el límite de análisis.')
    return path.read_text(encoding='utf-8',errors='replace')


def pdf_pages(path,directory):
    target=Path(directory)/'info.txt'
    # pdfinfo writes a bounded report; avoid storing document metadata in logs.
    limiter=shutil.which('prlimit')
    if not limiter:raise ExtractionError('El motor privado no está instalado.')
    with target.open('wb') as output:
        try:subprocess.run([limiter,'--as=536870912','--cpu=15','--fsize=1048576','--','pdfinfo',str(path)],stdout=output,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,timeout=20,check=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LC_ALL':'C','HOME':str(directory),'TMPDIR':str(directory)})
        except (OSError,subprocess.SubprocessError) as exc:raise ExtractionError('PDF ilegible, protegido o inválido.') from exc
    match=re.search(r'^Pages:\s+(\d+)',bounded_text(target),re.M)
    if not match:raise ExtractionError('No se pudo comprobar el número de páginas.')
    count=int(match[1])
    if count<1:raise ExtractionError('PDF sin páginas.')
    return count


def raster_pdf(path,page,directory,scale=1800):
    command(['pdftoppm','-f',page,'-l',page,'-singlefile','-scale-to',str(scale),'-png',path,Path(directory)/'page'],directory)
    result=Path(directory)/'page.png'
    if not result.exists() or result.stat().st_size>16_000_000:raise ExtractionError('Vista previa demasiado grande.')
    return result.read_bytes()


def image_dimensions(data,media):
    if media=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=24:
        width,height=struct.unpack('>II',data[16:24])
    elif media=='image/jpeg' and data.startswith(b'\xff\xd8'):
        pos=2;width=height=0
        while pos+8<len(data) and pos<1_000_000:
            if data[pos]!=255:pos+=1;continue
            marker=data[pos+1];pos+=2
            if marker in {0xD8,0xD9,0x01} or 0xD0<=marker<=0xD7:continue
            if pos+2>len(data):break
            length=int.from_bytes(data[pos:pos+2],'big')
            if length<2:break
            if marker in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF}:
                height,width=struct.unpack('>HH',data[pos+3:pos+7]);break
            pos+=length
    else:raise ExtractionError('Imagen no admitida.')
    if not width or not height or width*height>20_000_000 or max(width,height)>16000:raise ExtractionError('La imagen excede el tamaño seguro de visualización.')
    return width,height


def xml_member(archive,name):
    info=archive.getinfo(name)
    if info.file_size>8_000_000:raise ExtractionError('Parte de Word o Excel demasiado grande.')
    body=archive.read(name)
    if b'\x00' in body or b'<!doctype' in body.lower() or b'<!entity' in body.lower():raise ExtractionError('XML no admitido.')
    return ET.fromstring(body)


def office_text(data,media):
    validate_office(data,media);notes=[];parts=[]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=archive.namelist()
        if media.endswith('wordprocessingml.document'):
            for name in names:
                if name=='word/document.xml' or re.fullmatch(r'word/(header|footer)\d+\.xml',name):
                    root=xml_member(archive,name)
                    parts += [' '.join(t.text or '' for t in paragraph.iter() if t.tag.endswith('}t')) for paragraph in root.iter() if paragraph.tag.endswith('}p')]
        else:
            ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            strings=[]
            if 'xl/sharedStrings.xml' in names:
                strings=[''.join(t.itertext()) for t in xml_member(archive,'xl/sharedStrings.xml').findall('m:si',ns)]
            styles=[]
            if 'xl/styles.xml' in names:
                root=xml_member(archive,'xl/styles.xml');custom={int(n.get('numFmtId')):n.get('formatCode','') for n in root.findall('m:numFmts/m:numFmt',ns)}
                for style in root.findall('m:cellXfs/m:xf',ns):
                    number=int(style.get('numFmtId','0'));fmt=re.sub(r'"[^"]*"|\[[^]]*\]','',custom.get(number,''))
                    styles.append(14<=number<=22 or bool(re.search(r'[dy]',fmt,re.I)))
            epoch=datetime(1899,12,30)
            if 'xl/workbook.xml' in names:
                props=xml_member(archive,'xl/workbook.xml').find('m:workbookPr',ns)
                if props is not None and props.get('date1904') in {'1','true'}:epoch=datetime(1904,1,1)
            cells=0
            for name in names:
                if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml',name):continue
                root=xml_member(archive,name)
                for row in root.findall('.//m:row',ns):
                    values=[]
                    for cell in row.findall('m:c',ns):
                        cells+=1
                        if cells>20_000:raise ExtractionError('Excel excede el límite de celdas.')
                        if cell.find('m:f',ns) is not None:
                            if 'Excel contiene fórmulas sin evaluar.' not in notes:notes.append('Excel contiene fórmulas sin evaluar.')
                            continue
                        value=cell.findtext('m:v','',ns);kind=cell.get('t')
                        if kind=='s':value=strings[int(value)] if value.isdigit() and int(value)<len(strings) else ''
                        elif kind=='inlineStr':value=''.join(cell.find('m:is',ns).itertext()) if cell.find('m:is',ns) is not None else ''
                        elif kind=='d':value=value[:10]
                        elif value and int(cell.get('s','0'))<len(styles) and styles[int(cell.get('s','0'))]:
                            try:value=(epoch+timedelta(days=float(value))).date().isoformat()
                            except (ValueError,OverflowError):notes.append('Fecha numérica de Excel no interpretable.')
                        values.append(value)
                    parts.append(' | '.join(values))
    result='\n'.join(parts)
    if len(result)>MAX_TEXT:notes.append('Lectura parcial: texto demasiado largo.')
    return result[:MAX_TEXT],notes


def pdf_image_pages(path,directory,with_scans=False):
    target=Path(directory)/'images.txt'
    limiter=shutil.which('prlimit')
    if not limiter:raise ExtractionError('El motor privado no está instalado.')
    with target.open('wb') as output:
        try:subprocess.run([limiter,'--as=536870912','--cpu=15','--fsize=1048576','--','pdfimages','-list',str(path)],stdout=output,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,timeout=20,check=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LC_ALL':'C','HOME':str(directory),'TMPDIR':str(directory)})
        except (OSError,subprocess.SubprocessError) as exc:raise ExtractionError('No se pudo comprobar las imágenes del PDF.') from exc
    pages=set();scans=set()
    info=Path(directory)/'info.txt'
    size=re.search(r'Page size:\s+([0-9.]+) x ([0-9.]+)',bounded_text(info)) if info.exists() else None
    area=float(size[1])*float(size[2]) if size else None
    for line in bounded_text(target).splitlines():
        cells=line.split()
        if len(cells)>4 and cells[0].isdigit() and cells[3].isdigit() and cells[4].isdigit():
            width,height=int(cells[3]),int(cells[4])
            if max(width,height)>=500 and min(width,height)>=150:pages.add(int(cells[0]))
            if len(cells)>13 and area:
                try:
                    xppi,yppi=float(cells[12]),float(cells[13])
                    if xppi>0 and yppi>0 and width*height*72*72/(xppi*yppi)>=area*0.6:scans.add(int(cells[0]))
                except ValueError:pass
    return (pages,scans) if with_scans else pages


def ocr_deep(path,directory,notes):
    from document_analysis import parse_date,normalize,MONTHS
    token=r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+(?:de\s+)?(?:'+'|'.join(MONTHS)+r')\s+(?:de\s+)?\d{4})\b'
    readings=[]
    for mode in (3,6):
        local=[]
        try:text=ocr_text(path,directory,local,psm=mode)
        except ExtractionError:
            notes.append('OCR: no se completó una de las dos lecturas.');continue
        signatures=set()
        for match in re.finditer(token,normalize(text)):
            parsed=parse_date(match[0]);signatures.add(parsed.isoformat() if parsed else match[0])
        readings.append((text,local,signatures))
    if not readings:raise ExtractionError('No se completó la lectura OCR.')
    chosen=max(readings,key=lambda item:('OCR con confianza alta.' in item[1],len(item[0])))
    notes.extend(chosen[1])
    if len(readings)==2 and readings[0][2]!=readings[1][2]:notes.append('OCR: las dos lecturas no coinciden en las fechas; revisar.')
    return chosen[0]


def extract(data,media):
    if media.endswith(('wordprocessingml.document','spreadsheetml.sheet')):
        text,notes=office_text(data,media);return text,notes,'office'
    with tempfile.TemporaryDirectory(prefix='pagdoc-read-') as directory:
        os.chmod(directory,0o700);path=Path(directory)/('source.pdf' if media=='application/pdf' else 'source.img');path.write_bytes(data)
        notes=[];texts=[];ocr=False
        if media=='application/pdf':
            count=pdf_pages(path,directory)
            if count>MAX_PAGES:notes.append(f'Lectura parcial: PDF supera {MAX_PAGES} páginas.')
            image_pages,scan_pages=pdf_image_pages(path,directory,with_scans=True)
            started=time.monotonic()
            for page in range(1,min(count,MAX_PAGES)+1):
                if time.monotonic()-started>120:notes.append('Lectura parcial: tiempo máximo alcanzado.');break
                target=Path(directory)/'text.txt'
                command(['pdftotext','-f',page,'-l',page,'-layout',path,target],directory)
                text=bounded_text(target)
                from document_analysis import interpret
                digital=interpret(text)
                needs_ocr=len(re.sub(r'\s','',text))<30 or page in scan_pages or (page in image_pages and not digital['safe_to_apply'])
                if needs_ocr:
                    image=Path(directory)/'ocr.png';image.write_bytes(raster_pdf(path,page,directory,scale=3000));scanned=ocr_deep(image,directory,notes);text=text+'\n'+scanned;ocr=True
                texts.append(text)
                if sum(map(len,texts))>MAX_TEXT:notes.append('Lectura parcial: texto demasiado largo.');break
        elif media in {'image/png','image/jpeg'}:
            image_dimensions(data,media);texts.append(ocr_deep(path,directory,notes));ocr=True
        else:raise ExtractionError('Formato no admitido.')
        return '\n'.join(texts)[:MAX_TEXT],notes,'ocr' if ocr else 'pdf_text'


def ocr_text(path,directory,notes=None,psm=3):
    target=Path(directory)/'ocr-result'
    command(['tesseract',path,target,'-l','spa+eng','--psm',str(psm),'txt','tsv'],directory,timeout=40)
    rows=list(csv.DictReader(io.StringIO(bounded_text(target.with_suffix('.tsv'))),delimiter='\t'))
    words=[row for row in rows if row.get('text','').strip()]
    scores=[float(row['conf']) for row in words]
    numeric=[float(row['conf']) for row in words if re.search(r'\d',row['text'])]
    clear=bool(scores) and min(scores)>=60 and sum(scores)/len(scores)>=85 and (not numeric or min(numeric)>=90)
    if notes is not None:
        notes.append('OCR con confianza alta.' if clear else 'OCR con confianza insuficiente: revisar lectura.')
    return bounded_text(target.with_suffix('.txt'))
