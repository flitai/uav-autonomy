// ===============================================================================
// Authors: AFRL/RQQD
// Organization: Air Force Research Laboratory, Aerospace Systems Directorate, Power and Control Division
// 
// Copyright (c) 2017 Government of the United State of America, as represented by
// the Secretary of the Air Force.  No copyright is claimed in the United States under
// Title 17, U.S. Code.  All Other Rights Reserved.
// ===============================================================================




package avtas.amase.analysis;

import afrl.cmasi.AirVehicleState;
import afrl.cmasi.PointSearchTask;
import afrl.cmasi.SearchTask;
import afrl.cmasi.WavelengthBand;
import avtas.map.graphics.MapMarker;
import java.awt.Color;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Path2D;
import java.util.HashMap;
import java.util.Map;
import java.util.TreeMap;

/**
 * Performs point search coverage analysis.
 * @author AFRL/RQQD
 */
public class PointSearchHighlight extends MapMarker implements SearchGraphic {

    private PointSearchTask task = null;
    private SearchPixel[][] pixMap = new SearchPixel[1][1];
    private final Map<String, Observation> previous = new HashMap<>();
    private final TreeMap<Long, Long> intervals = new TreeMap<>();
    private boolean observed;

    private static final class Observation {
        final long time;
        final boolean qualified;
        Observation(long time, boolean qualified) { this.time = time; this.qualified = qualified; }
    }

    /**
     * Constructs a new point search highlighter for the specified search task.
     * @param task The search task to manage.
     */
    public PointSearchHighlight(PointSearchTask task) {
        this.task = task;
        this.pixMap[0][0] = new SearchPixel(task.getSearchLocation().getLatitude(),
                task.getSearchLocation().getLongitude());
        setLat(task.getSearchLocation().getLatitude());
        setLon(task.getSearchLocation().getLongitude());
        initialize();
    }

    /** {@inheritDoc} */
    public SearchPixel[][] getPixels() {
        return pixMap;
    }

    /** {@inheritDoc} */
    public void initialize() {
        pixMap[0][0].seen = false;
        pixMap[0][0].timeFirstSeen = 0;
        pixMap[0][0].totalTimeSeen = 0;
        previous.clear();
        intervals.clear();
        observed = false;
        setFill(FILL_COLOR);
        setPainter(FILL_COLOR, 1);
        setMarkerShape(new Ellipse2D.Float(0, 0, 10, 10));
        setVisible(false);
    }

    /** {@inheritDoc} */
    public void processSensor(AirVehicleState avs, CameraModel model, double aglAlt) {

        String sensor = avs.getID() + ":" + model.getCameraID();
        Observation last = previous.get(sensor);
        long time = avs.getTime();
        if (last != null && time <= last.time) return;
        Path2D footprint = model.getFootprint(avs);
        SearchPixel p = pixMap[0][0];
        boolean qualified = (task.getDesiredWavelengthBands().contains(model.getCameraConfig().getSupportedWavelengthBand())
                || task.getDesiredWavelengthBands().contains(WavelengthBand.AllAny))
                && footprint != null && p.inSensorFOV(footprint)
                && model.computeGSD(avs, p, aglAlt) <= task.getGroundSampleDistance();
        previous.put(sensor, new Observation(time, qualified));
        if (!qualified) return;
        if (!observed) { p.timeFirstSeen = time; observed = true; }
        // Count sampled observation intervals, in source milliseconds. Both
        // endpoints must qualify on the same camera. Missing samples beyond
        // twice the analysis cadence do not prove continuous observation.
        if (last != null && last.qualified && time - last.time <= 2000 * AnalysisClient.CHECK_TIME) {
            addInterval(last.time, time, p);
        }
        if (p.totalTimeSeen >= task.getDwellTime()) { p.seen = true; setVisible(true); }
    }

    private void addInterval(long start, long end, SearchPixel p) {
        Map.Entry<Long, Long> entry = intervals.floorEntry(start);
        if (entry != null && entry.getValue() >= start) {
            start = entry.getKey(); end = Math.max(end, entry.getValue());
            p.totalTimeSeen -= entry.getValue() - entry.getKey(); intervals.remove(entry.getKey());
        }
        entry = intervals.ceilingEntry(start);
        while (entry != null && entry.getKey() <= end) {
            end = Math.max(end, entry.getValue());
            p.totalTimeSeen -= entry.getValue() - entry.getKey(); intervals.remove(entry.getKey());
            entry = intervals.ceilingEntry(start);
        }
        intervals.put(start, end); p.totalTimeSeen += end - start;
    }

    /** {@inheritDoc} */
    public SearchTask getTask() {
        return task;
    }
}

/* Distribution A. Approved for public release. 
 *  Case: #88ABW-2015-4601. Date: 24 Sep 2015. */
