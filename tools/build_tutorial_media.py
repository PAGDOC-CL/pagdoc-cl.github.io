"""Build silent, captioned instructional MP4s with fictitious schematic UI.
Requires Pillow and ffmpeg. Run from the repository root. No network or real data.
"""
import json,math,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
LESSONS=json.loads((ROOT/'assets/tutorial-lessons.json').read_text())
W,H,FPS=1280,720,12
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
def f(n,bold=False):return ImageFont.truetype(BOLD if bold else FONT,n)
NAV=['Mi operación','Servicios','Planificador','Empresa y vehículos','Revisión documental','Pendientes','Cierre documental','Usuarios y acceso','Integraciones','Mi seguridad']
BLUE='#103652';CYAN='#46d4d2';INK='#16354c';GRAY='#5f7485'
def wrap(draw,text,font,width):
    lines=[];line=''
    for word in text.split():
        trial=(line+' '+word).strip()
        if draw.textlength(trial,font=font)>width and line:lines.append(line);line=word
        else:line=trial
    return lines+[line]
def label(d,xy,text,size=23,color=INK,bold=False):d.text(xy,text,font=f(size,bold),fill=color)
def card(d,box,title,detail,accent=CYAN):
    d.rounded_rectangle(box,16,fill='white',outline='#d9e4ed',width=2)
    x,y,_,_=box;d.rounded_rectangle((x+18,y+20,x+25,y+67),3,fill=accent)
    label(d,(x+42,y+16),title,24,bold=True)
    for i,line in enumerate(wrap(d,detail,f(20),box[2]-x-70)):label(d,(x+42,y+56+26*i),line,20,GRAY)
def base(lesson,index):
    im=Image.new('RGB',(W,H),'#edf3f8');d=ImageDraw.Draw(im)
    d.rectangle((0,0,250,568),fill=BLUE);label(d,(25,24),'PAGDOC',32,'white',True);label(d,(25,68),'GUÍA DE LA PLATAFORMA',13,CYAN)
    for n,name in enumerate(NAV):
        y=116+n*40
        if name==lesson['nav']:d.rounded_rectangle((12,y-6,239,y+29),7,fill='#205570')
        label(d,(24,y),name,16,'white' if name==lesson['nav'] else '#b7cedc',name==lesson['nav'])
    label(d,(286,23),'APRENDIZAJE · EJEMPLO FICTICIO',16,GRAY,True)
    label(d,(286,57),lesson['title'],32,INK,True)
    d.line((286,111,1245,111),fill='#d0dee8',width=2)
    nav=lesson['nav']
    if nav=='Planificador':
        label(d,(310,135),'MES DE EJEMPLO',20,GRAY,True)
        for n in range(21):
            x=307+(n%7)*130;y=181+(n//7)*96
            d.rounded_rectangle((x,y,x+118,y+84),7,fill='white',outline='#dce5ed')
            label(d,(x+11,y+8),str(n+1),18)
            state=['Terreno','Terreno','Descanso','Sin asignar'][n%4]
            color=['#c8f1e9','#c8f1e9','#d7e7ff','#edf0f3'][n%4]
            d.rounded_rectangle((x+8,y+42,x+110,y+73),4,fill=color)
            label(d,(x+13,y+48),state,13)
    elif nav=='Empresa y vehículos':
        for n,(t,v) in enumerate([('Empresa de ejemplo','Documento de seguridad · Pendiente'),('Vehículo FICT01','Carpeta / inspección.pdf · Versión 2'),('Historial conservado','Versión anterior disponible con sesión')]):card(d,(300,140+n*126,1230,250+n*126),t,v)
    elif nav=='Servicios':
        card(d,(300,145,745,410),'SERV-EJEMPLO-01','Proyecto ficticio · Planta Norte\nUbicación y fechas del servicio')
        card(d,(770,145,1230,410),'SERV-EJEMPLO-02','Proyecto ficticio · Planta Sur\nConsulta su ficha y planificación')
    elif nav=='Revisión documental':
        for n,(t,v) in enumerate([('Archivo y requisitos','Revisar el contenido y su vigencia'),('Evaluación pendiente','Aprobar · Observar · Rechazar'),('Motivo y trazabilidad','La decisión queda registrada')]):card(d,(300,140+n*126,1230,250+n*126),t,v)
    elif nav=='Usuarios y acceso':
        for n,(t,v) in enumerate([('administrador@example.invalid','Administrador · Activo'),('planificador@example.invalid','Planificador · Sin lectura documental'),('visor@example.invalid','Consulta · Sin modificaciones')]):card(d,(300,140+n*126,1230,250+n*126),t,v)
    elif nav=='Mi seguridad':
        card(d,(300,145,1230,285),'Perfil de ejemplo','Rol autorizado · Control de sesiones')
        card(d,(300,310,1230,482),'Alertas por correo','Anticipación: 30 días · Correo registrado\nEnvío pendiente de configurar en este ejemplo')
    elif nav=='Integraciones':
        for n,(t,v) in enumerate([('Archivos privados','Sesión · Cifrado · Análisis antimalware'),('Correo de alertas','Requiere cuenta de envío y preferencias'),('Microsoft SharePoint','Requiere autorización propia de la aplicación')]):card(d,(300,140+n*126,1230,250+n*126),t,v)
    elif nav=='Cierre documental':
        for n,(t,v) in enumerate([('Servicio de ejemplo','Requisitos y evidencias relacionados'),('Comprobación de pendientes','Faltantes y observaciones por resolver'),('Resultado del cierre','Validación según permisos y requisitos')]):card(d,(300,140+n*126,1230,250+n*126),t,v)
    elif nav=='Pendientes':
        for n,(t,v) in enumerate([('Revisar evidencia ficticia','Responsable: Usuario de ejemplo · Pendiente'),('Coordinar planificación','Comprobar fechas y servicio'),('Regularizar documento','Registrar el avance real de la tarea')]):card(d,(300,140+n*126,1230,250+n*126),t,v)
    else:
        for n,(title,num) in enumerate([('Servicios activos','2'),('Pendientes','3'),('Por revisar','1')]):
            x=300+n*315;card(d,(x,145,x+295,310),title,'Ejemplo ficticio');label(d,(x+40,244),num,46,INK,True)
        card(d,(300,340,1230,493),'Prioridades de hoy','Abre el módulo para consultar cada registro')
    d.rectangle((0,568,W,H),fill='#08283e')
    title,body=lesson['slides'][index]
    label(d,(32,585),f'{index+1:02d}  {title}',28,'white',True)
    for i,line in enumerate(wrap(d,body,f(24),1200)):label(d,(32,629+i*30),line,24,'#d6eaf3')
    return im

def build(key,lesson):
    output=ROOT/'assets'/f'tutorial-{key}.mp4'
    frames_per_slide=FPS*5
    cmd=['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','28','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    total=len(lesson['slides'])*frames_per_slide
    for index in range(len(lesson['slides'])):
        background=base(lesson,index)
        for frame in range(frames_per_slide):
            im=background.copy();d=ImageDraw.Draw(im);t=frame/frames_per_slide
            # An animated pointer and focus border guide attention without fake clicks.
            x=int(340+530*min(t*1.8,1));y=165+index*87
            y=min(y,465)
            pulse=int(5+4*math.sin(t*math.pi))
            d.ellipse((x-15-pulse,y-15-pulse,x+15+pulse,y+15+pulse),outline='#0b9b9c',width=3)
            d.polygon([(x,y),(x+7,y+28),(x+14,y+18),(x+26,y+17)],fill='#103652',outline='white')
            d.rectangle((0,710,int(W*(index*frames_per_slide+frame+1)/total),719),fill=CYAN)
            process.stdin.write(im.tobytes())
    process.stdin.close()
    if process.wait()!=0:raise RuntimeError('Video encoding failed')
    print(output.name,output.stat().st_size,flush=True)

if __name__=='__main__':
    for key,lesson in LESSONS.items():build(key,lesson)
