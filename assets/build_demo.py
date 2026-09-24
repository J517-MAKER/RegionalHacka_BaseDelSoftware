"""Ilustraciones vectoriales originales; ninguna imagen representa una persona real."""
from pathlib import Path
import math
import struct
import wave

ROOT = Path(__file__).resolve().parent / 'demo'


def svg(content,width=1200,height=700):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">{content}</svg>'


def build_assets():
    ROOT.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'test-tone.wav').exists():
        with wave.open(str(ROOT/'test-tone.wav'),'wb') as audio:
            audio.setparams((1,2,16000,0,'NONE','not compressed'))
            audio.writeframes(b''.join(struct.pack('<h',int(2500*math.sin(2*math.pi*440*i/16000)) if i%8000<4000 else 0) for i in range(32000)))
    if (ROOT/'map.svg').exists():
        return
    blocks=[]
    for row in range(7):
        for col in range(11):
            x,y=col*116-35,row*112-15
            blocks.append(f'<rect x="{x}" y="{y}" width="92" height="86" rx="3" fill="#e2e5df" stroke="#d1d7d0"/>')
            for dx,dy,w,h in [(7,7,33,30),(45,7,38,30),(7,43,76,34)]:
                blocks.append(f'<rect x="{x+dx}" y="{y+dy}" width="{w}" height="{h}" fill="#d6dbd4" stroke="#ccd3cb"/>')
    blocks.extend(['<path d="M-20 575L1240 235" stroke="#d2dacf" stroke-width="85"/><path d="M-20 575L1240 235" stroke="#f9faf7" stroke-width="66"/>',
                   '<path d="M830 -10L1090 720" stroke="#d7deda" stroke-width="60"/><path d="M830 -10L1090 720" stroke="#c9dce1" stroke-width="43"/>',
                   '<rect x="415" y="246" width="228" height="159" fill="#d1dfc9" stroke="#bdcfb8"/>',
                   '<path d="M415 324H643M529 246V405" stroke="#edf1e4" stroke-width="14"/>',
                   '<circle cx="529" cy="324" r="32" fill="#e9ede4" stroke="#c2cdbf"/><circle cx="529" cy="324" r="13" fill="#b9d1d6"/>',
                   '<rect x="58" y="10" width="177" height="156" rx="5" fill="#d0dfc7"/>',
                   '<path d="M69 25L220 147M70 145L220 25" stroke="#e7eddc" stroke-width="8"/>'])
    for x,y in [(430,266),(615,270),(432,382),(615,382),(79,52),(116,105),(184,54),(191,131)]:
        blocks.append(f'<circle cx="{x}" cy="{y}" r="13" fill="#b8cdb0"/><circle cx="{x-3}" cy="{y-3}" r="8" fill="#c4d5bb"/>')
    labels=[(125,85,'PARQUE NORTE'),(530,353,'PLAZA DE LA REPÚBLICA'),(310,93,'COLONIA ALAMEDA'),(803,130,'ESTACIÓN CENTRAL'),
            (161,647,'BARRIO PONIENTE'),(742,605,'DISTRITO CENTRO'),(385,476,'AV. REPÚBLICA'),(740,359,'AV. REFORMA'),
            (1048,480,'RÍO DEL CENTRO'),(278,217,'CALLE HIDALGO'),(580,664,'AV. UNIVERSIDAD')]
    for x,y,label in labels:
        blocks.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="10" fill="#8a978d" text-anchor="middle" letter-spacing="1.8">{label}</text>')
    blocks.append('<path d="M1140 53l-8 22 8-5 8 5z" fill="#6c7d80"/><text x="1140" y="45" text-anchor="middle" font-family="Arial" font-size="11" fill="#6c7d80">N</text>')
    (ROOT/'map.svg').write_text(svg('<rect width="1200" height="700" fill="#f3f4ef"/>'+''.join(blocks)),encoding='utf-8')
    for i in range(1,5):
        hair=['#403a34','#302b29','#5d4235','#2d3035'][i-1]
        shirt=['#3b596d','#6b7161','#675268','#4b6775'][i-1]
        portrait=f'''<rect width="500" height="600" fill="#dce1e2"/>
        <rect x="22" y="22" width="456" height="556" fill="#d0d7d9" stroke="#b9c4c9"/>
        <path d="M88 600V489Q98 405 208 398H292Q402 412 412 489V600" fill="{shirt}"/>
        <path d="M214 354H286V427L250 459L214 427" fill="#bd9680"/>
        <ellipse cx="250" cy="257" rx="105" ry="143" fill="{hair}"/>
        <ellipse cx="158" cy="284" rx="17" ry="25" fill="#c9a08a"/><ellipse cx="341" cy="284" rx="17" ry="25" fill="#c9a08a"/>
        <path d="M166 235Q167 167 251 166Q334 167 334 241L325 328Q313 378 252 397Q187 379 177 328Z" fill="#d3ac95"/>
        <path d="M154 255Q151 125 257 127Q359 142 346 265L321 219Q283 210 250 176Q217 218 177 218L164 274Z" fill="{hair}"/>
        <path d="M193 265Q210 256 228 265M272 265Q290 256 307 265" fill="none" stroke="{hair}" stroke-width="5"/>
        <ellipse cx="211" cy="280" rx="5" ry="6" fill="#4b433e"/><ellipse cx="290" cy="280" rx="5" ry="6" fill="#4b433e"/>
        <path d="M251 280L241 312Q250 317 260 312" fill="none" stroke="#ac8372" stroke-width="3"/>
        <path d="M225 341Q250 350 277 339" fill="none" stroke="#996e63" stroke-width="3"/>
        <path d="M206 408L249 460L223 485L180 423M293 408L250 460L276 485L320 424" fill="none" stroke="#92a2a8" stroke-width="2"/>
        <rect y="554" width="500" height="46" fill="#203645"/>
        <text x="250" y="582" fill="#e0e8ec" text-anchor="middle" font-family="Arial" font-size="14" letter-spacing="2">PERSONA FICTICIA · REFERENCIA {i:02d}</text>'''
        (ROOT/f'person-{i}.svg').write_text(svg(portrait,500,600),encoding='utf-8')
        if i==1:
            (ROOT/'capture.svg').write_text(svg(portrait.replace('#dce1e2','#a8b5b5')+'<rect x="140" y="120" width="218" height="292" fill="none" stroke="#d0b771" stroke-width="3"/><text x="150" y="108" font-family="monospace" fill="#283d4a" font-size="15">CAM-003 / MUESTRA SINTÉTICA</text>',500,600),encoding='utf-8')
    for i in range(1,4):
        scene=f'''<rect width="960" height="540" fill="#9daaad"/>
        <path d="M0 210L960 170V540H0" fill="#b5b9b3"/>
        <path d="M0 0H960V115L0 265Z" fill="#7c8b91"/>
        <path d="M0 46L570 102V215L0 329Z" fill="#b7bbb6"/>
        <path d="M0 75L570 126V145L0 102ZM0 187L570 166V185L0 219Z" fill="#63767f"/>
        <path d="M74 78V289M181 88V269M295 99V247M411 111V224M523 120V207" stroke="#d8dad1" stroke-width="14"/>
        <path d="M660 0H960V267L660 199Z" fill="#c7cac0"/>
        <path d="M696 42V204M774 39V221M860 36V242M941 30V260" stroke="#647981" stroke-width="37"/>
        <path d="M0 540L557 215M234 540L602 215M630 540L675 215M960 500L719 214" stroke="#8b9899" stroke-width="2"/>
        <path d="M0 455H960M0 358H960M0 287H960" stroke="#909c9c" stroke-width="2"/>
        <path d="M0 535L540 225" stroke="#d9dcd2" stroke-width="26"/>
        <rect x="734" y="263" width="125" height="11" fill="#566963"/><path d="M747 274V301M846 274V301" stroke="#51655f" stroke-width="5"/>
        <rect x="416" y="151" width="3" height="130" fill="#4a6167"/><rect x="391" y="148" width="54" height="9" fill="#e0e4d5"/>
        <ellipse cx="172" cy="323" rx="43" ry="10" fill="#697d74"/><rect x="169" y="230" width="9" height="94" fill="#6a7667"/>
        <circle cx="171" cy="218" r="42" fill="#778c79"/><circle cx="156" cy="197" r="31" fill="#819382"/>
        <g transform="translate({480+i*35},{272+i*11}) scale(.85)"><ellipse cx="0" cy="67" rx="24" ry="7" fill="#788b8c"/><circle cy="-23" r="10" fill="#c1ac98"/><path d="M-10-10H11L19 28H-17Z" fill="#3b5867"/><path d="M-7 27L-11 65M8 27L14 65" stroke="#374951" stroke-width="9"/></g>
        <g transform="translate(652,244) scale(.55)"><circle cy="-23" r="10" fill="#bfae9e"/><path d="M-10-10H11L19 28H-17Z" fill="#8f8575"/><path d="M-7 27L-11 65M8 27L14 65" stroke="#505858" stroke-width="9"/></g>
        <text x="22" y="515" fill="#edf0e9" font-family="monospace" font-size="13" letter-spacing="2">ESCENA SINTÉTICA · SIN TRANSMISIÓN REAL</text>'''
        (ROOT/f'cctv-{i}.svg').write_text(svg(scene,960,540),encoding='utf-8')
