"""Read-only PMTiles v3 audit. Complete directories; bounded representative MVT reads.

Specification: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
No HTTP server or whole-archive decompression is used here.
"""
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
import time
import zlib

import numpy as np


def need(value, message):
    if not value: raise ValueError(message)


def inflate(data, maximum=32*1024*1024):
    decoder = zlib.decompressobj(31)
    result = decoder.decompress(data, maximum+1)
    need(len(result) <= maximum and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
         'Invalid, concatenated or oversized gzip member')
    return result


def varints(data):
    """Vectorized, bounded uint64 varints, including overflow/truncation checks."""
    b = np.frombuffer(data, dtype=np.uint8)
    if not len(b): return np.array([], dtype=np.uint64)
    ends = np.flatnonzero(b < 128)
    need(len(ends) and ends[-1] == len(b)-1, 'Truncated varint')
    starts = np.r_[0, ends[:-1]+1]; sizes = ends-starts+1
    need(sizes.max() <= 10 and np.all(b[ends[sizes == 10]] <= 1), 'Varint overflow')
    shifts = (np.arange(len(b))-np.repeat(starts, sizes)).astype(np.uint64)*7
    return np.bitwise_or.reduceat((b.astype(np.uint64) & 127) << shifts, starts)


def directory(data):
    values = varints(inflate(data))
    need(len(values) and 0 < values[0] <= 1000000, 'Invalid directory count')
    count = int(values[0]); need(len(values) == 1+4*count, 'Directory length differs')
    ids = np.cumsum(values[1:1+count], dtype=np.uint64)
    runs = values[1+count:1+2*count]; lengths = values[1+2*count:1+3*count]
    encoded = values[1+3*count:]
    need(np.all(ids[1:] > ids[:-1]) and np.all(lengths > 0) and encoded[0] > 0, 'Invalid directory entries')
    # Offset zero refers to the preceding end; each explicit offset begins a group.
    preceding = np.r_[np.uint64(0), np.cumsum(lengths[:-1], dtype=np.uint64)]
    explicit = np.flatnonzero(encoded)
    group = np.maximum.accumulate(np.where(encoded != 0, np.arange(count), 0))
    offsets = encoded[group]-1 + preceding-preceding[group]
    need(np.all(offsets <= np.iinfo(np.int64).max) and np.all(lengths <= 32*1024*1024), 'Directory offset/length overflow')
    return ids, runs, lengths, offsets


def tile_id(z, x, y):
    need(0 <= z <= 26 and 0 <= x < 2**z and 0 <= y < 2**z, 'Invalid XYZ')
    n = 2**z; d = 0; step = n//2
    while step:
        rx = int(bool(x & step)); ry = int(bool(y & step))
        d += step*step*((3*rx)^ry)
        if ry == 0:
            if rx: x, y = n-1-x, n-1-y
            x, y = y, x
        step //= 2
    return (4**z-1)//3+d


class Archive:
    def __init__(self, path):
        self.path = Path(path); self.file = self.path.open('rb'); self.size = self.path.stat().st_size
        try:
            h = self.read(0,127); need(h[:8] == b'PMTiles\x03', 'Not PMTiles v3')
            keys = ('rootOffset','rootLength','metadataOffset','metadataLength','leafOffset','leafLength',
                    'tileOffset','tileLength','addressedTiles','tileEntries','tileContents')
            self.header = dict(zip(keys, struct.unpack_from('<11Q',h,8)))
            self.header.update(clustered=h[96], internalCompression=h[97], tileCompression=h[98],
                               tileType=h[99], minZoom=h[100], maxZoom=h[101],
                               bounds=[v/1e7 for v in struct.unpack_from('<4i',h,102)])
            a = self.header
            need(h[96:100] == bytes([1,2,2,1]), 'Unsupported clustered/compression/type combination')
            need(0 <= a['minZoom'] <= a['maxZoom'] <= 26, 'Invalid zoom range')
            w,s,e,n = a['bounds']; need(-180 <= w < e <= 180 and -90 <= s < n <= 90, 'Invalid bounds')
            spans = sorted((a[k+'Offset'], a[k+'Length']) for k in ('root','metadata','leaf','tile'))
            last = 127
            for offset,length in spans:
                need(offset >= last and offset+length <= self.size, 'Overlapping/out-of-file section')
                last = offset+length
            need(a['rootOffset']+a['rootLength'] <= 16384, 'Root exceeds first 16 KiB')
            self.metadata = json.loads(inflate(self.read(a['metadataOffset'], a['metadataLength'])))
            need(isinstance(self.metadata,dict) and isinstance(self.metadata.get('vector_layers'),list), 'Missing vector metadata')
        except BaseException:
            self.file.close(); raise

    def close(self): self.file.close()

    def read(self, offset, length):
        need(0 <= offset <= self.size and 0 <= length <= min(self.size-offset,32*1024*1024), 'Invalid bounded read')
        self.file.seek(offset); result = self.file.read(length)
        need(len(result) == length, 'Short archive read'); return result

    def walk(self):
        a = self.header; visited = set(); spans = []
        lower = (4**a['minZoom']-1)//3; upper = (4**(a['maxZoom']+1)-1)//3
        def visit(offset,length,low,high,depth):
            need(depth <= 4 and (offset,length) not in visited, 'Repeated/cyclic/deep directory')
            visited.add((offset,length))
            ids,runs,lengths,offsets = directory(self.read(offset,length))
            need(int(ids[0]) >= low and int(ids[-1]) < high, 'Directory key outside parent range')
            if np.all(runs > 0):
                need(np.all(ids[:-1]+runs[:-1] <= ids[1:]) and int(ids[-1])+int(runs[-1]) <= high,
                     'Overlapping/out-of-range tile runs')
                need(np.all(offsets+lengths <= a['tileLength']), 'Tile data outside section')
                yield ids,runs,lengths,offsets
            else:
                # Producers here use homogeneous directories. Mixed directories are
                # supported by visiting one data entry or leaf at a time.
                for i in range(len(ids)):
                    limit = int(ids[i+1]) if i+1 < len(ids) else high
                    if runs[i]:
                        need(int(ids[i])+int(runs[i]) <= limit and int(offsets[i])+int(lengths[i]) <= a['tileLength'], 'Bad data entry')
                        yield tuple(v[i:i+1] for v in (ids,runs,lengths,offsets))
                    else:
                        begin,end = int(offsets[i]),int(offsets[i]+lengths[i])
                        need(end <= a['leafLength'], 'Leaf outside section')
                        spans.append((begin,end))
                        yield from visit(a['leafOffset']+begin,end-begin,int(ids[i]),limit,depth+1)
        yield from visit(a['rootOffset'],a['rootLength'],lower,upper,0)
        previous = 0
        for begin,end in sorted(spans):
            need(begin == previous, 'Unused/overlapping leaf bytes'); previous=end
        need(previous == a['leafLength'], 'Unreferenced leaf section tail')
        self.directory_count = len(visited)

    def audit(self, scratch, progress=None):
        """All entries and distinct blob references, with a disk-backed end index.

        Clustered first occurrences must pack the data section. Back references
        must resolve to an exact previously seen blob (offset AND length).
        """
        a = self.header; start = time.monotonic(); count=addressed=unique=frontier=last_id=0
        ends = np.memmap(scratch,mode='w+',dtype='<u8',shape=(a['tileContents'],))
        for ids,runs,lengths,offsets in self.walk():
            need(int(ids[0]) >= last_id, 'Cross-directory tile overlap')
            next_ends = offsets+lengths
            maxima = np.maximum.accumulate(np.r_[np.uint64(frontier),next_ends])
            fresh = next_ends > maxima[:-1]
            need(np.all(offsets[fresh] == maxima[:-1][fresh]), 'Unclustered or gapped tile data')
            new = int(fresh.sum()); need(unique+new <= len(ends), 'Too many distinct contents')
            ends[unique:unique+new] = next_ends[fresh]; unique += new
            reused = ~fresh
            if np.any(reused):
                found = np.searchsorted(ends[:unique],next_ends[reused])
                need(np.all(found < unique), 'Unknown deduplication reference')
                begins = np.where(found == 0,0,ends[np.maximum(found,1)-1])
                need(np.all(ends[found] == next_ends[reused]) and np.all(begins == offsets[reused]), 'Partial blob deduplication reference')
            count += len(ids); addressed += int(runs.sum()); frontier = int(maxima[-1])
            last_id = int(ids[-1])+int(runs[-1])
            if progress and count//5000000 != (count-len(ids))//5000000:
                progress(dict(entries=count,expected=a['tileEntries'],elapsedSeconds=time.monotonic()-start))
        ends.flush(); del ends
        need((count,addressed,unique,frontier) == (a['tileEntries'],a['addressedTiles'],a['tileContents'],a['tileLength']),
             'Header counters or complete tile byte coverage differs')
        return dict(entries=count,addressedTiles=addressed,distinctContents=unique,directories=self.directory_count,
                    allIndexEntriesChecked=True,allTilePayloadsDecoded=False,
                    scratchBytes=a['tileContents']*8,elapsedSeconds=time.monotonic()-start)

    def tile(self,z,x,y):
        key = tile_id(z,x,y); a = self.header; offset,length = a['rootOffset'],a['rootLength']
        for depth in range(5):
            ids,runs,lengths,offsets = directory(self.read(offset,length))
            i = int(np.searchsorted(ids,key,side='right'))-1
            need(i >= 0, 'Representative tile missing')
            if runs[i]:
                need(key < int(ids[i])+int(runs[i]), 'Representative tile missing')
                data = self.read(a['tileOffset']+int(offsets[i]),int(lengths[i]))
                return inflate(data),dict(z=z,x=x,y=y,tileId=str(key),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            offset,length = a['leafOffset']+int(offsets[i]),int(lengths[i])
        raise ValueError('Directory depth limit')


def fields(data):
    cursor = 0
    def varint():
        nonlocal cursor
        value=0
        for shift in range(0,70,7):
            need(cursor < len(data), 'Truncated protobuf'); b=data[cursor];cursor+=1
            need(shift < 63 or b <= 1, 'Protobuf integer overflow'); value |= (b & 127)<<shift
            if b < 128: return value
        raise ValueError('Invalid protobuf varint')
    while cursor < len(data):
        key = varint(); number,wire = key>>3,key&7; need(number>0, 'Invalid protobuf field')
        if wire==0: value=varint()
        else:
            length = varint() if wire==2 else {1:8,5:4}.get(wire)
            need(length is not None and length <= len(data)-cursor, 'Unsupported/truncated protobuf wire')
            value=data[cursor:cursor+length];cursor+=length
        yield number,wire,value


def inspect_mvt(data):
    layers=[]; labels=[]
    for number,wire,value in fields(data):
        if number != 3: continue
        need(wire==2,'Invalid layer wire'); props=list(fields(value))
        names=[v.decode('utf-8') for n,w,v in props if n==1 and w==2]
        versions=[v for n,w,v in props if n==15 and w==0]
        extents=[v for n,w,v in props if n==5 and w==0]
        need(len(names)==len(versions)==1 and versions[0] in (1,2) and len(extents)<=1, 'Invalid MVT layer')
        extent=extents[0] if extents else 4096;need(0 < extent <= 65536,'MVT extent')
        keys=[v.decode('utf-8') for n,w,v in props if n==3 and w==2]
        vals=[list(fields(v)) for n,w,v in props if n==4 and w==2]
        for item in vals:
            known=[(n,w,v) for n,w,v in item if n in range(1,8)]
            need(len(known)==1,'MVT value must have one type')
            n,w,v=known[0]
            if n==1:
                need(w==2,'String wire');text=v.decode('utf-8')
                if any('\u4e00'<=c<='\u9fff' for c in text) and len(labels)<8:labels.append(text[:160])
        features=0;vertices=0
        for n,w,feature in props:
            if n != 2:continue
            need(w==2,'Feature wire'); fs=list(fields(feature));features+=1
            kind=[v for n,w,v in fs if n==3 and w==0];need(len(kind)==1 and kind[0] in (1,2,3),'Unknown geometry')
            for n,w,v in fs:
                if n==2:
                    need(w==2,'Tags wire'); tags=varints(v)
                    need(len(tags)%2==0 and np.all(tags[::2]<len(keys)) and np.all(tags[1::2]<len(vals)),'Bad tag dictionary index')
                if n==4:
                    need(w==2,'Geometry wire');g=varints(v);i=0;x=y=0;has_move=False
                    while i<len(g):
                        command=int(g[i]);i+=1;op,count=command&7,command>>3
                        need(op in (1,2,7) and count>0,'Invalid geometry command')
                        if op==7:need(kind[0]==3 and count==1 and has_move,'Invalid ClosePath');continue
                        need(op==1 or has_move,'LineTo without MoveTo')
                        need(i+2*count<=len(g),'Truncated geometry')
                        if op==1:has_move=True
                        if kind[0]==1:need(op==1,'Point contains LineTo')
                        for j in range(count):
                            dx,dy=int(g[i]),int(g[i+1]);i+=2
                            x+=(dx>>1)^-(dx&1);y+=(dy>>1)^-(dy&1);vertices+=1
                            need(abs(x)<2**31 and abs(y)<2**31,'Geometry coordinate overflow')
        layers.append(dict(name=names[0],version=versions[0],extent=extent,features=features,vertices=vertices))
    need(layers and len({v['name'] for v in layers})==len(layers),'Missing/duplicate MVT layers')
    return dict(layers=layers,chineseLabels=labels)


def representatives(archive):
    result=[];maximum=archive.header['maxZoom']
    for z in range(maximum+1):
        n=2**z
        for lon,lat in ((-120.9645,45.323),(116.397,39.908)):
            x=int((lon+180)/360*n);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
            if any(r['z']==z and r['x']==x and r['y']==y for r in result):continue
            data,row=archive.tile(z,x,y);row.update(inspect_mvt(data));result.append(row)
    return result
