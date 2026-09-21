"""Measure actual screenshot pixels without importing browser rendering code."""
import struct
import zlib


def pixels(png):
    assert png[:8]==b'\x89PNG\r\n\x1a\n'
    cursor=8;compressed=b''
    while cursor<len(png):
        size=struct.unpack_from('>I',png,cursor)[0];kind=png[cursor+4:cursor+8];data=png[cursor+8:cursor+8+size]
        if kind==b'IHDR':
            width,height,depth,color,compression,filtering,interlace=struct.unpack('>2I5B',data)
            assert depth==8 and color in (2,6) and interlace==0
        if kind==b'IDAT':compressed+=data
        cursor+=size+12
    channels=3 if color==2 else 4;stride=width*channels;raw=zlib.decompress(compressed);previous=bytearray(stride)
    output=[]
    for y in range(height):
        start=y*(stride+1);kind=raw[start];row=bytearray(raw[start+1:start+1+stride])
        for x in range(stride):
            a=row[x-channels] if x>=channels else 0;b=previous[x];c=previous[x-channels] if x>=channels else 0
            if kind==1:v=a
            elif kind==2:v=b
            elif kind==3:v=(a+b)//2
            elif kind==4:
                p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);v=a if pa<=pb and pa<=pc else b if pb<=pc else c
            else:assert kind==0;v=0
            row[x]=(row[x]+v)&255
        output.append(row);previous=row
    return width,height,channels,output


def measure(png,red=False):
    width,height,channels,rows=pixels(png)
    # Camera is centred on selected entity; controls, labels and trails excluded.
    points={}
    for y in range(max(0,height//2-260),min(height,height//2+260)):
        for x in range(max(0,width//2-260),min(width,width//2+260)):
            r,g,b=rows[y][x*channels:x*channels+3]
            match=(r>90 and r>g*1.6 and r>b*1.3) if red else (g>75 and b>90 and g>r*1.8 and b>r*1.8)
            if match:points[(x,y)]=max(r,g,b)
    components=[]
    while points:
        seed=next(iter(points));todo=[seed];part=[]
        while todo:
            p=todo.pop()
            if p not in points:continue
            value=points.pop(p);part.append((*p,value));x,y=p
            todo.extend([(x-1,y),(x+1,y),(x,y-1),(x,y+1)])
        components.append(part)
    assert components,'No coloured model pixels in view'
    part=max(components,key=len);values=sorted(p[2] for p in part)
    low,high=values[len(values)//10],values[len(values)*9//10]
    return dict(pixels=len(part),width=max(p[0] for p in part)-min(p[0] for p in part)+1,height=max(p[1] for p in part)-min(p[1] for p in part)+1,
                brightness10=low,brightness90=high,brightnessSpan=high-low,levels=len(set(values)))
