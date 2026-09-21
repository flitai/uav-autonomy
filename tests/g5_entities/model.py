"""Independent GLB container, geometry, axes, UV and embedded PNG comparison."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

source,path,output=map(Path,sys.argv[1:]);data=path.read_bytes();scene=json.loads((source/'scene.json').read_text())
magic,version,length=struct.unpack_from('<III',data);assert (magic,version,length)==(0x46546c67,2,len(data))
length,kind=struct.unpack_from('<II',data,12);assert kind==0x4e4f534a
model=json.loads(data[20:20+length]);offset=20+length;size,kind=struct.unpack_from('<II',data,offset);assert kind==0x004e4942
binary=data[offset+8:];assert len(binary)==size and model['asset']['version']=='2.0'
assert not model.get('animations') and not model.get('skins') and all('uri' not in row for row in model['buffers']+model['images'])
def view(index):
 row=model['bufferViews'][index];start=row.get('byteOffset',0);size=row['byteLength'];assert start%4==0 and start+size<=len(binary)
 return binary[start:start+size]
def accessor(index,width):
 row=model['accessors'][index];assert row['componentType']==5126 and row['type']=={2:'VEC2',3:'VEC3'}[width]
 values=list(struct.iter_unpack('<'+'f'*width,view(row['bufferView'])));assert len(values)==row['count'];return values
errors=[];images=[];triangles=0
for index,mesh in enumerate(model['meshes']):
 primitive=mesh['primitives'][0];assert primitive['mode']==4
 original=list(struct.iter_unpack('<8f',(source/f'mesh-{index}.f32').read_bytes()))
 points=accessor(primitive['attributes']['POSITION'],3);uv=accessor(primitive['attributes']['TEXCOORD_0'],2);normals=accessor(primitive['attributes']['NORMAL'],3)
 assert len(points)==len(original)==len(normals)==len(uv);triangles+=len(points)//3
 for row,p,n,t in zip(original,points,normals,uv):
  # Compare preserved source axis landmarks under an independently written rotation.
  errors += [abs(p[0]-row[0]),abs(p[1]-row[2]),abs(p[2]+row[1]),abs(n[0]-row[3]),abs(n[1]-row[5]),abs(n[2]+row[4]),abs(t[0]-row[6]),abs(t[1]+row[7]-1)]
 material=model['materials'][primitive['material']];assert material['pbrMetallicRoughness']['baseColorFactor']==scene['meshes'][index]['diffuse']
 if 'texture' in scene['meshes'][index]:
  texture=material['pbrMetallicRoughness']['baseColorTexture']['index'];image=model['images'][model['textures'][texture]['source']];png=view(image['bufferView'])
  assert png[:8]==b'\x89PNG\r\n\x1a\n';cursor=8;compressed=b''
  while cursor<len(png):
   length=struct.unpack_from('>I',png,cursor)[0];kind=png[cursor+4:cursor+8];payload=png[cursor+8:cursor+8+length]
   assert zlib.crc32(kind+payload)&0xffffffff==struct.unpack_from('>I',png,cursor+8+length)[0]
   if kind==b'IHDR':width,height,depth,color,*_=struct.unpack('>2I5B',payload);assert (depth,color)==(8,6)
   if kind==b'IDAT':compressed+=payload
   cursor+=12+length
  decoded=zlib.decompress(compressed);assert len(decoded)==height*(width*4+1)
  assert all(decoded[y*(width*4+1)]==0 for y in range(height))
  rgba=b''.join(decoded[y*(width*4+1)+1:(y+1)*(width*4+1)] for y in range(height))
  assert rgba==(source/f'image-{index}.rgba').read_bytes()
  alpha=sorted(set(rgba[3::4]));assert material['alphaMode']=='BLEND' if min(alpha)<255 else material['alphaMode']=='OPAQUE'
  images.append(dict(width=width,height=height,rgbaBytes=len(rgba),alphaValues=alpha,sha256=hashlib.sha256(rgba).hexdigest()))
assert max(errors)<1e-6
result=dict(status='passed',triangles=triangles,meshes=len(model['meshes']),images=images,maximumTransformError=max(errors),externalResources=0,sourceUnitsPerMeter=1)
output.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
