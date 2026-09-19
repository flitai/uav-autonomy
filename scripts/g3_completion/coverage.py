"""Independent audit of the frozen WaterwaySearch coverage contract (no score floor)."""
import base64
import csv
import math
from pathlib import Path
import xml.etree.ElementTree as ET


def need(value, reason):
    if not value:
        raise RuntimeError(reason)


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6378137 * 2 * math.asin(min(1, math.sqrt(h)))


def inside(lat, lon, polygon):
    # Ray crossing, separately implemented from java.awt.Path2D.
    crossings = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[0] > lat) != (b[0] > lat):
            x = a[1] + (lat-a[0])*(b[1]-a[1])/(b[0]-a[0])
            if lon < x: crossings = not crossings
    return crossings


def grid(task):
    points = [(float(p.findtext('Latitude')), float(p.findtext('Longitude'))) for p in task.findall('PointList/Location3D')]
    need(len(points) == 90, 'coverage-full-waterway-missing')
    cells = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        steps = int(distance(a, b)/20) + 1
        for j in range(steps):
            cells.append(dict(row=i, column=j, latitude=a[0]+(b[0]-a[0])*j/steps,
                              longitude=a[1]+(b[1]-a[1])*j/steps))
    return cells


def inspect(report, details, expected_cells):
    lines = report.findall('.//SearchTaskAnalysis/SearchLine')
    need(len(lines) == 1 and lines[0].get('ID') == '1000', 'coverage-task-report-missing')
    line = lines[0]
    total, seen = int(line.findtext('TotalCells')), int(line.findtext('SeenCells'))
    need(total > 0 and 0 <= seen <= total, 'coverage-count-range')
    need(total == len(expected_cells), 'coverage-denominator')
    percent = 100*seen/total
    need(abs(float(line.findtext('CoveragePercent'))-percent) <= 0.00500001, 'coverage-report-percent')
    need(float(details.get('GridResolutionMeters')) == 20, 'coverage-grid-resolution')
    tasks = details.findall('Task')
    need(len(tasks) == 1 and tasks[0].get('ID') == '1000', 'coverage-cell-task')
    pixels = tasks[0].findall('Cell')
    need(len(pixels) == total, 'coverage-cell-export-incomplete')
    result = []
    for expected, cell in zip(expected_cells, pixels):
        need(int(cell.get('row')) == expected['row'] and int(cell.get('column')) == expected['column'], 'coverage-cell-identity')
        need(abs(float(cell.get('latitude'))-expected['latitude']) < 1e-10 and
             abs(float(cell.get('longitude'))-expected['longitude']) < 1e-10, 'coverage-cell-coordinate')
        need(cell.get('seen') in ('true', 'false'), 'coverage-cell-seen-invalid')
        result.append(dict(expected, seen=cell.get('seen') == 'true'))
    need(sum(p['seen'] for p in result) == seen, 'coverage-seen-count')
    return dict(taskId='1000', gridResolutionMeters=20, total=total, seen=seen, unseen=total-seen,
                coveragePercent=percent, reportCoveragePercent=line.findtext('CoveragePercent')), result


def independent_replay(events_path, cells):
    seen, configurations, state_count = set(), {}, 0
    task = None
    with events_path.open(encoding='utf-8') as source:
        for line in source:
            _, encoded = line.strip().split('\t', 1)
            n = ET.fromstring(base64.b64decode(encoded))
            if n.tag == 'AirVehicleConfiguration': configurations[n.findtext('ID')] = n
            elif n.tag == 'LineSearchTask':
                need(task is None and n.findtext('TaskID') == '1000', 'replay-task-duplicate')
                task = n
                need(n.findtext('DwellTime') == '0', 'independent-replay-requires-original-zero-dwell')
            elif n.tag == 'AirVehicleState' and task is not None:
                state_count += 1
                config = configurations.get(n.findtext('ID'))
                need(config is not None, 'replay-state-without-configuration')
                desired = [b.text for b in task.findall('DesiredWavelengthBands/WavelengthBand')]
                av = n.find('Location/Location3D')
                pos = float(av.findtext('Latitude')), float(av.findtext('Longitude'))
                for camera in config.findall('PayloadConfigurationList/CameraConfiguration'):
                    cid = camera.findtext('PayloadID')
                    linked = any(cid in [x.text for x in g.findall('ContainedPayloadList/int64')]
                                 for g in config.findall('PayloadConfigurationList/GimbalConfiguration'))
                    if not linked: continue
                    if 'AllAny' not in desired and camera.findtext('SupportedWavelengthBand') not in desired: continue
                    states = [s for s in n.findall('PayloadStateList/CameraState') if s.findtext('PayloadID') == cid]
                    need(len(states) == 1, 'replay-camera-state-missing')
                    camera_state = states[0]
                    footprint = camera_state.findall('Footprint/Location3D')
                    polygon = [(float(p.findtext('Latitude')), float(p.findtext('Longitude'))) for p in footprint]
                    # This run has no DTED; require the captured footprints to confirm zero elevation.
                    need(all(float(p.findtext('Altitude')) == 0 for p in footprint), 'independent-replay-terrain-assumption')
                    if len(polygon) < 3: continue
                    west, east = min(p[1] for p in polygon), max(p[1] for p in polygon)
                    south, north = min(p[0] for p in polygon), max(p[0] for p in polygon)
                    resolution = int(camera.findtext('VideoStreamHorizontalResolution'))
                    need(resolution > 0, 'replay-camera-resolution')
                    pixel_angle = math.radians(float(camera_state.findtext('HorizontalFieldOfView')))/resolution
                    for index, cell in enumerate(cells):
                        if index in seen: continue
                        lat, lon = cell['latitude'], cell['longitude']
                        if not (west <= lon <= east and south <= lat <= north and inside(lat, lon, polygon)): continue
                        slant = math.hypot(distance(pos, (lat, lon)), float(av.findtext('Altitude')))
                        if slant*math.sin(pixel_angle) <= float(task.findtext('GroundSampleDistance')): seen.add(index)
    need(task is not None and state_count > 0, 'coverage-empty-replay')
    return seen, state_count


def assess(directory, original_task):
    amase = directory / 'amase'
    summary, cells = inspect(ET.parse(amase/'analysis.xml').getroot(), ET.parse(amase/'coverage-cells.xml').getroot(), grid(original_task))
    seen, states = independent_replay(amase/'analysis-events.tsv', cells)
    need(seen == {i for i, p in enumerate(cells) if p['seen']}, 'coverage-independent-replay-differs')
    with (directory/'uncovered.csv').open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=['row', 'column', 'latitude', 'longitude', 'seen'])
        writer.writeheader(); writer.writerows(p for p in cells if not p['seen'])
    summary.update(independentReplayStates=states, independentReplayMatched=True, terrain='zero-elevation-fallback', minimumCoveragePercent=None)
    return summary
