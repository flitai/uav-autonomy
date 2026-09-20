"""Synthetic capability probes; never qualifies real terrain or a vertical datum."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image
import pyproj
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    pyproj.network.set_network_enabled(False)
    rgb = np.array([[[128, 0, 0], [127, 255, 128]], [[128, 100, 64], [129, 0, 0]]], dtype=np.uint8)
    path = args.output/'synthetic.png'; Image.fromarray(rgb).save(path)
    with Image.open(path) as source: np.testing.assert_array_equal(np.asarray(source), rgb)
    heights = rgb[..., 0].astype(float)*256 + rgb[..., 1] + rgb[..., 2]/256 - 32768
    np.testing.assert_array_equal(heights, [[0, -0.5], [100.25, 256]])
    grid = ((np.arange(1201*1201).reshape(1201, 1201) % 900)-300).astype('int16')
    grid[20, 30] = -32767
    transform = from_origin(-0.5/1200, 1+0.5/1200, 1/1200, 1/1200)
    with rasterio.Env(GDAL_CACHEMAX=32*1024*1024, DTED_VERIFY_CHECKSUM='YES') as environment:
        drivers = environment.drivers()
        assert {'GTiff', 'PNG', 'DTED'} <= drivers.keys(), drivers
        with rasterio.open(args.output/'synthetic.tif', 'w', driver='GTiff', width=1201, height=1201,
                           count=1, dtype='int16', crs='EPSG:4326', transform=transform, nodata=-32767) as target:
            target.write(grid, 1)
        raster_copy(args.output/'synthetic.tif', args.output/'synthetic.dt1', driver='DTED')
        with rasterio.open(args.output/'synthetic.dt1') as source:
            np.testing.assert_array_equal(source.read(1), grid)
            assert source.width == source.height == 1201 and source.crs.to_epsg() == 4326
            assert source.nodata == -32767 and source.transform.almost_equals(transform)
    xyz = pyproj.Transformer.from_crs(4979, 4978, always_xy=True).transform(0, 0, 100)
    np.testing.assert_allclose(xyz, (6378237, 0, 0), atol=1e-6)
    try:
        pyproj.Transformer.from_pipeline('+proj=vgridshift +grids=missing-g5-required-grid.tif')
    except pyproj.exceptions.ProjError: pass
    else: raise AssertionError('Missing required transformation grid accepted')
    result = dict(status='passed', python=sys.version, gdal=rasterio.__gdal_version__,
                  rasterioProj=rasterio.__proj_version__, pyprojProj=pyproj.proj_version_str,
                  versions={d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
                  drivers={key:drivers[key] for key in ('GTiff', 'PNG', 'DTED')},
                  projNetworkEnabled=pyproj.network.is_network_enabled(), syntheticOnly=True,
                  checks=['PNG-RGB', 'Terrarium-formula-positive-negative', 'GTiff-DTED1-roundtrip',
                          'nodata', 'georeferencing', 'WGS84-ECEF', 'missing-grid-refused'])
    (args.output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__': main()
