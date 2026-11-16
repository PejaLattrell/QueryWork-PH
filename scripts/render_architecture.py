"""Render the repository architecture as editable SVG and a matching PNG.

Run from any directory with Python and Pillow. This is documentation tooling;
the application and ingestion package do not depend on Pillow.
"""
from html import escape
from math import hypot
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, SCALE = 1600, 1080, 2
INK, MUTED, LINE = '#173248', '#536a7d', '#8295a5'


class Diagram:
    def __init__(self):
        self.image = Image.new('RGB', (WIDTH * SCALE, HEIGHT * SCALE), 'white')
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
                    '<title id="title">QueryWork PH: Python ingestion architecture</title>',
                    '<desc id="desc">Current local Python collector, durable response files, Supabase and FastAPI dashboard. Planned Databricks managed volume, Bronze, Silver, Gold and validated snapshot publication.</desc>',
                    '<rect width="1600" height="1080" fill="white"/>']

    def font(self, size, bold):
        names = ([r'C:/Windows/Fonts/seguisb.ttf', 'DejaVuSans-Bold.ttf'] if bold
                 else [r'C:/Windows/Fonts/segoeui.ttf', 'DejaVuSans.ttf'])
        for name in names:
            try:
                return ImageFont.truetype(name, size * SCALE)
            except OSError:
                pass
        return ImageFont.load_default(size=size * SCALE)

    def text(self, x, y, value, size=18, color=INK, bold=False, center=False):
        anchor = 'mm' if center else 'lm'
        self.draw.text((x * SCALE, y * SCALE), value, font=self.font(size, bold), fill=color, anchor=anchor)
        self.svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-family="Segoe UI, DejaVu Sans, Arial, sans-serif" font-size="{size}" font-weight="{600 if bold else 400}" text-anchor="{"middle" if center else "start"}" dominant-baseline="central">{escape(value)}</text>')

    def rect(self, x, y, w, h, fill, outline=LINE, radius=16):
        self.draw.rounded_rectangle((x*SCALE,y*SCALE,(x+w)*SCALE,(y+h)*SCALE), radius=radius*SCALE, fill=fill, outline=outline, width=2*SCALE)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{outline}" stroke-width="2"/>')

    def arrow(self, points, dashed=False, color=LINE):
        for (x1,y1),(x2,y2) in zip(points,points[1:]):
            length=hypot(x2-x1,y2-y1)
            if dashed and length:
                for start in range(0,int(length),14):
                    end=min(start+8,length)
                    self.draw.line(((x1+(x2-x1)*start/length)*SCALE,(y1+(y2-y1)*start/length)*SCALE,
                                    (x1+(x2-x1)*end/length)*SCALE,(y1+(y2-y1)*end/length)*SCALE),fill=color,width=2*SCALE)
            else:
                self.draw.line((x1*SCALE,y1*SCALE,x2*SCALE,y2*SCALE),fill=color,width=2*SCALE)
        (px,py),(x,y)=points[-2:]
        length=hypot(x-px,y-py)
        dx,dy=(x-px)/length,(y-py)/length
        tip=[(x,y),(x-dx*10-dy*5,y-dy*10+dx*5),(x-dx*10+dy*5,y-dy*10-dx*5)]
        self.draw.polygon([(a*SCALE,b*SCALE) for a,b in tip],fill=color)
        dash=' stroke-dasharray="8 6"' if dashed else ''
        self.svg.append(f'<polyline points="{" ".join(f"{a},{b}" for a,b in points)}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
        self.svg.append(f'<polygon points="{" ".join(f"{a},{b}" for a,b in tip)}" fill="{color}"/>')

    def card(self, x, y, w, title, lines, fill='#ffffff', outline=LINE, height=132):
        self.rect(x,y,w,height,fill,outline)
        self.text(x+w/2,y+32,title,23,bold=True,center=True)
        for i,line in enumerate(lines):
            self.text(x+w/2,y+66+i*26,line,17,color=MUTED,center=True)

    def save(self):
        target=ROOT/'docs'
        target.mkdir(exist_ok=True)
        (target/'architecture.svg').write_text('\n'.join(self.svg+['</svg>']),encoding='utf-8')
        self.image.save(target/'architecture.png',optimize=True)


def main():
    d=Diagram()
    d.text(60,42,'QUERYWORK PH',17,color='#177c70',bold=True)
    d.text(60,90,'Python ingestion architecture',36,bold=True)
    d.text(60,130,'Current local pipeline and planned lakehouse path',20,color=MUTED)
    d.rect(40,170,1520,390,'#f1f8f7',outline='#b6d7d0',radius=22)
    d.text(60,198,'CURRENT IMPLEMENTATION',17,color='#177c70',bold=True)
    d.card(60,236,260,'Job feeds',['Remotive + Arbeitnow','Bounded API requests'])
    d.card(370,236,340,'Python ingestion',['CLI or dashboard trigger','Fetch / normalize / batch writes'],fill='#e3f3ef',outline='#258b7d')
    d.card(780,236,300,'Supabase Postgres',['job_postings + scrape_runs','Prototype serving tables'])
    d.card(1150,236,320,'Local dashboard',['FastAPI + Jinja / HTMX','JSON API + Chart.js'])
    for left,right in ((320,370),(710,780),(1080,1150)):
        d.arrow([(left,302),(right,302)])
    d.card(370,416,340,'Durable response files',['Original bytes + metadata + hash','Replay from local landing'],height=116,fill='#ffffff',outline='#258b7d')
    d.arrow([(540,368),(540,416)],color='#258b7d')
    d.text(60,444,'Run on demand.',19,bold=True)
    d.text(60,474,'No automatic schedule enabled.',17,color=MUTED)
    d.text(780,444,'Write key stays server-side.',18,bold=True)
    d.text(780,474,'Dashboard reads use a separate key.',17,color=MUTED)
    d.text(780,504,'Batch failures are recorded explicitly.',17,color=MUTED)
    d.rect(40,610,1520,310,'#f5f6fb',outline='#c4cbe1',radius=22)
    d.text(60,642,'PLANNED DATABRICKS PATH',17,color='#566aa5',bold=True)
    d.text(60,678,'External upload, Bronze loading, transformations, and snapshot publication still require implementation and verification.',18,color=MUTED)
    positions=[(60,220),(306,190),(522,190),(738,190),(954,246),(1226,314)]
    nodes=[('Managed volume',['Original batches','Verified upload']),('Bronze',['Source identity','Posting versions']),
           ('Silver',['Standardized fields','Strong-evidence links']),('Gold',['Curated listings','Dashboard aggregates']),
           ('Batch publisher',['Stage and validate','Publish one version']),('Supabase snapshot',['Last successful publication','Read by the same dashboard'])]
    for (x,w),(title,lines) in zip(positions,nodes):
        d.card(x,732,w,title,lines,outline='#9ba9ce',height=136)
    for (x,w),(next_x,_) in zip(positions,positions[1:]):
        d.arrow([(x+w,800),(next_x,800)],dashed=True,color='#7e8fb9')
    d.arrow([(540,532),(540,584),(20,584),(20,800),(60,800)],dashed=True,color='#7e8fb9')
    d.text(60,968,'Local availability',19,bold=True)
    d.text(60,1000,'The collector and dashboard require this PC awake. Local schedules stop while it is off.',18,color=MUTED)
    d.text(60,1030,'Hosted schedules and processing remain subject to source permissions, verified free-tier limits, and a proven storage handoff.',17,color=MUTED)
    d.save()
    print('Rendered docs/architecture.svg and docs/architecture.png')


if __name__=='__main__':
    main()
