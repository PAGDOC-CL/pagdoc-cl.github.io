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
MAX_PAGES=12


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


def extract(data,media):
    if media.endswith(('wordprocessingml.document','spreadsheetml.sheet')):
        text,notes=office_text(data,media);return text,notes,'office'
    with tempfile.TemporaryDirectory(prefix='pagdoc-read-') as directory:
        os.chmod(directory,0o700);path=Path(directory)/('source.pdf' if media=='application/pdf' else 'source.img');path.write_bytes(data)
        notes=[];texts=[];ocr=False
        if media=='application/pdf':
            count=pdf_pages(path,directory)
            if count>MAX_PAGES:notes.append('Lectura parcial: PDF supera 12 páginas.')
            started=time.monotonic()
            for page in range(1,min(count,MAX_PAGES)+1):
                if time.monotonic()-started>90:notes.append('Lectura parcial: tiempo máximo alcanzado.');break
                target=Path(directory)/'text.txt'
                command(['pdftotext','-f',page,'-l',page,'-layout',path,target],directory)
                text=bounded_text(target)
                if len(re.sub(r'\s','',text))<30:
                    image=Path(directory)/'ocr.png';image.write_bytes(raster_pdf(path,page,directory,scale=3000));text=ocr_text(image,directory);ocr=True
                texts.append(text)
                if sum(map(len,texts))>MAX_TEXT:notes.append('Lectura parcial: texto demasiado largo.');break
        elif media in {'image/png','image/jpeg'}:
            image_dimensions(data,media);texts.append(ocr_text(path,directory));ocr=True
        else:raise ExtractionError('Formato no admitido.')
        if ocr:notes.append('Lectura OCR: las fechas requieren confirmación visual.')
        return '\n'.join(texts)[:MAX_TEXT],notes,'ocr' if ocr else 'pdf_text'


def ocr_text(path,directory):
    target=Path(directory)/'ocr-result'
    command(['tesseract',path,target,'-l','spa+eng','--psm','3'],directory,timeout=40)
    return bounded_text(target.with_suffix('.txt'))
