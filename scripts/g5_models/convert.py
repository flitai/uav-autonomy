"""Convert the selected, inspected static mesh into self-contained glTF 2.0."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

def png(width,height,rgba):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,9))+chunk(b'IEND',b'')

def convert(source,output,meters_per_unit):
    source=Path(source);output=Path(output);scene=json.loads((source/'scene.json').read_text(encoding='utf-8'))
    assert scene['osgVersion']=='3.6.5' and scene['animations']==0 and 0<meters_per_unit<=100
    document=dict(asset={'version':'2.0','generator':'uav-autonomy G5 static OSGB conversion'},scene=0,scenes=[{'nodes':[]}],
        nodes=[],meshes=[],materials=[],accessors=[],bufferViews=[],buffers=[{}],images=[],textures=[],samplers=[])
    binary=bytearray();all_positions=[];image_records=[];normal_error=0
    def view(data,target=None):
        while len(binary)%4:binary.append(0)
        record=dict(buffer=0,byteOffset=len(binary),byteLength=len(data));binary.extend(data)
        if target:record['target']=target
        document['bufferViews'].append(record);return len(document['bufferViews'])-1
    def accessor(rows,width,with_bounds=False):
        data=b''.join(struct.pack('<'+'f'*width,*row) for row in rows)
        entry=dict(bufferView=view(data,34962),componentType=5126,count=len(rows),type={2:'VEC2',3:'VEC3'}[width])
        if with_bounds:entry.update(min=[min(p[i] for p in rows) for i in range(width)],max=[max(p[i] for p in rows) for i in range(width)])
        document['accessors'].append(entry);return len(document['accessors'])-1
    for index,mesh in enumerate(scene['meshes']):
        rows=list(struct.iter_unpack('<8f',(source/f'mesh-{index}.f32').read_bytes()))
        assert len(rows)==mesh['vertices'] and len(rows)%3==0
        # Source nose -Y, upper surface +Z. Proper rotation (determinant +1):
        # glTF +Z nose, +Y up, +X left. Cesium maps this to +X/+Z forward/up.
        positions=[(p[0]*meters_per_unit,p[2]*meters_per_unit,-p[1]*meters_per_unit) for p in rows]
        normals=[(p[3],p[5],-p[4]) for p in rows]
        normal_error=max(normal_error,max(abs(sum(v*v for v in n)-1) for n in normals))
        assert normal_error<1e-5,'Nonunit normals'
        uvs=[(p[6],1-p[7]) for p in rows];all_positions.extend(positions)
        material=dict(pbrMetallicRoughness=dict(baseColorFactor=mesh['diffuse'],metallicFactor=0,roughnessFactor=1),doubleSided=True)
        if 'texture' in mesh:
            image=mesh['texture'];rgba=(source/f'image-{index}.rgba').read_bytes()
            assert len(rgba)==image['width']*image['height']*4
            encoded=png(image['width'],image['height'],rgba)
            document['images'].append(dict(bufferView=view(encoded),mimeType='image/png'))
            document['samplers'].append(dict(wrapS=image['wrapS'],wrapT=image['wrapT'],magFilter=9729,minFilter=9987))
            document['textures'].append(dict(source=len(document['images'])-1,sampler=len(document['samplers'])-1))
            material['pbrMetallicRoughness']['baseColorTexture']=dict(index=len(document['textures'])-1)
            material['alphaMode']='BLEND' if image['transparentPixels'] or mesh['diffuse'][3]<1 else 'OPAQUE'
            image_records.append(dict(width=image['width'],height=image['height'],rgbaSHA256=hashlib.sha256(rgba).hexdigest(),pngSHA256=hashlib.sha256(encoded).hexdigest(),transparentPixels=image['transparentPixels']))
            (output.parent/f'texture-{index}.png').write_bytes(encoded)
        document['materials'].append(material)
        attributes={'POSITION':accessor(positions,3,True),'NORMAL':accessor(normals,3),'TEXCOORD_0':accessor(uvs,2)}
        document['meshes'].append(dict(primitives=[dict(attributes=attributes,material=index,mode=4)]))
        document['nodes'].append(dict(mesh=index,name='AFSIM UCAV display mesh '+str(index)))
        document['scenes'][0]['nodes'].append(index)
    document['buffers'][0]['byteLength']=len(binary)
    encoded=json.dumps(document,separators=(',',':'),ensure_ascii=True).encode()
    encoded+=b' '*((-len(encoded))%4);binary.extend(b'\0'*((-len(binary))%4))
    glb=struct.pack('<III',0x46546c67,2,12+8+len(encoded)+8+len(binary))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
    output.write_bytes(glb)
    mins=[min(p[i] for p in all_positions) for i in range(3)];maxs=[max(p[i] for p in all_positions) for i in range(3)]
    record=dict(status='converted',sourceReader=scene,bytes=len(glb),sha256=hashlib.sha256(glb).hexdigest(),
        meshes=len(scene['meshes']),triangles=len(all_positions)//3,positions=len(all_positions),images=image_records,
        min=mins,max=maxs,dimensionsMeters=[b-a for a,b in zip(mins,maxs)],metersPerSourceUnit=meters_per_unit,
        sourceForward='-Y',sourceUp='+Z',gltfForward='+Z',gltfUp='+Y',origin='Original local origin retained; not asserted to be centre of gravity',
        normalLengthSquaredError=normal_error,externalResources=[],animations=0,
        materialMapping='Diffuse times embedded RGBA; PBR metallic=0 roughness=1; alpha preserved; no claim of identical legacy lighting')
    output.with_suffix('.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record
