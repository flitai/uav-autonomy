"""Turn a validated G6 task draft into the qualified LMCP scene task."""
import math
import mmap
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/g6_tasks'))
import baseline


def ground_height(grid_path, lon, lat):
    baseline.need(-122 <= lon <= -120 and 45 <= lat <= 46, 'Ground point outside canonical grid')
    x, y = (lon + 122) * 1200, (46 - lat) * 1200
    i, j = min(math.floor(x), 2399), min(math.floor(y), 1199)
    dx, dy = x - i, y - j
    with grid_path.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as grid:
        baseline.need(len(grid) == 1201 * 2401 * 4, 'Canonical grid dimensions changed')
        def cell(row, column):
            value = struct.unpack_from('<f', grid, (row * 2401 + column) * 4)[0]
            baseline.need(math.isfinite(value) and value >= 0, 'Canonical grid height invalid')
            return value
        return ((cell(j, i) * (1 - dx) + cell(j, i + 1) * dx) * (1 - dy)
                + (cell(j + 1, i) * (1 - dx) + cell(j + 1, i + 1) * dx) * dy)


def set_location(node, coordinate, grid):
    lon, lat = coordinate
    baseline.need(node is not None, 'Task location template missing')
    node.find('Longitude').text = format(lon, '.14g')
    node.find('Latitude').text = format(lat, '.14g')
    node.find('Altitude').text = format(ground_height(grid, lon, lat), '.12g')
    node.find('AltitudeType').text = 'MSL'


def build(draft, contract, scene, terrain, output):
    baseline.validate_draft(draft, contract)
    spec = contract['taskTypes'][draft['kind']]
    baseline.need(draft['taskId'] == spec['baselineTaskId'], 'Task ID outside first batch')
    source = scene / ('task-' + draft['taskId'] + '.xml')
    tree = ET.parse(source)
    root = tree.getroot()
    baseline.need(root.tag == spec['lmcpType'].split('.')[-1], 'Task template type differs')
    grid = terrain / 'orthometric.f32'
    baseline.need(grid.is_file(), 'Qualified terrain grid missing')
    geometry = draft['geometry']
    if draft['kind'] == 'point':
        set_location(root.find('SearchLocation/Location3D'), geometry['coordinates'], grid)
    elif draft['kind'] == 'line':
        points = root.find('PointList')
        baseline.need(points is not None and len(points) > 0, 'Line template missing')
        exemplar = points[0]
        for node in list(points):
            points.remove(node)
        import copy
        for coordinate in geometry['coordinates']:
            node = copy.deepcopy(exemplar)
            set_location(node, coordinate, grid)
            points.append(node)
    else:
        rectangle = root.find('SearchArea/Rectangle')
        set_location(rectangle.find('CenterPoint/Location3D'), geometry['center'], grid)
        rectangle.find('Width').text = format(geometry['widthMeters'], '.12g')
        rectangle.find('Height').text = format(geometry['heightMeters'], '.12g')
        rectangle.find('Rotation').text = '0'
    tree.write(output, encoding='utf-8', xml_declaration=True)
    return output
