package avtas.amase.analysis;

import afrl.cmasi.*;
import avtas.amase.scenario.ScenarioState;
import avtas.app.Context;
import avtas.util.NavUtils;
import avtas.xml.Element;
import avtas.xml.XmlReader;
import java.awt.geom.Path2D;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/** Deterministic small fixtures, independent of the flight/planning algorithm. */
public final class CoverageChecks {
    private static int failures;
    private static final Element results = new Element("CoverageChecks");

    private static void check(String name, long expected, long actual) {
        Element e = new Element("Check");
        e.setAttribute("name", name); e.setAttribute("expected", String.valueOf(expected));
        e.setAttribute("actual", String.valueOf(actual));
        e.setAttribute("passed", String.valueOf(expected == actual)); results.add(e);
        if (expected != actual) failures++;
    }

    static Location3D location(double lat, double lon) {
        Location3D p = new Location3D(); p.setLatitude(lat); p.setLongitude(lon); return p;
    }

    static LineSearchTask task(WavelengthBand band, double lengthDegrees) {
        LineSearchTask t = new LineSearchTask(); t.setTaskID(1000);
        t.getDesiredWavelengthBands().clear(); t.getDesiredWavelengthBands().add(band);
        t.setGroundSampleDistance(1); t.setDwellTime(0);
        t.getPointList().add(location(0, 0)); t.getPointList().add(location(0, lengthDegrees));
        return t;
    }

    static long count(SearchGraphic g, boolean seenOnly) {
        long n = 0;
        for (SearchGraphic.SearchPixel[] row : g.getPixels()) for (SearchGraphic.SearchPixel p : row)
            if (p != null && (!seenOnly || p.seen)) n++;
        return n;
    }

    static class Camera extends CameraModel {
        final Path2D shape = new Path2D.Double();
        double gsd = 0.5;
        Camera(double west, double east) {
            super(new AirVehicleConfiguration(), new CameraConfiguration(), new GimbalConfiguration());
            getCameraConfig().setSupportedWavelengthBand(WavelengthBand.EO);
            shape.moveTo(west, -1); shape.lineTo(east, -1); shape.lineTo(east, 1); shape.lineTo(west, 1); shape.closePath();
        }
        @Override public Path2D getFootprint(AirVehicleState s) { return shape; }
        @Override public double computeGSD(AirVehicleState s, SearchGraphic.SearchPixel p, double altitude) { return gsd; }
    }

    public static void main(String[] args) throws Exception {
        AirVehicleState state = new AirVehicleState(); state.setTime(1000);
        Camera partial = new Camera(-0.00001, 0.00018), full = new Camera(-1, 1);
        LinearSearchHighlight g = new LinearSearchHighlight(20, task(WavelengthBand.EO, 0.00036));
        check("manual-three-cells", 3, count(g, false));
        check("unobserved", 0, count(g, true));
        g.processSensor(state, partial, 100); check("manual-two-of-three", 2, count(g, true));
        g.processSensor(state, partial, 100); check("duplicate-deduplicated", 2, count(g, true));
        g.processSensor(state, full, 100); check("all-covered", 3, count(g, true));
        g.initialize(); check("graphic-reset", 0, count(g, true));
        g.processSensor(state, new Camera(1, 2), 100); check("outside-footprint", 0, count(g, true));
        full.gsd = 1.01; g.processSensor(state, full, 100); check("gsd-too-coarse", 0, count(g, true));
        full.gsd = 1; g.processSensor(state, full, 100); check("gsd-boundary", 3, count(g, true));
        for (WavelengthBand band : new WavelengthBand[]{WavelengthBand.EO, WavelengthBand.LWIR, WavelengthBand.AllAny}) {
            g = new LinearSearchHighlight(20, task(band, 0.00036));
            g.processSensor(state, full, 100);
            check("band-" + band, band == WavelengthBand.LWIR ? 0 : 3, count(g, true));
        }
        LineSearchTask dwell = task(WavelengthBand.EO, 0.00036); dwell.setDwellTime(1000);
        g = new LinearSearchHighlight(20, dwell); g.processSensor(state, full, 100);
        check("dwell-not-yet", 0, count(g, true)); state.setTime(1999); g.processSensor(state, full, 100);
        check("dwell-before-boundary", 0, count(g, true)); state.setTime(2000); g.processSensor(state, full, 100);
        check("dwell-millisecond-boundary", 3, count(g, true));
        g = new LinearSearchHighlight(20, task(WavelengthBand.EO, 0.01));
        long expected = (long)(NavUtils.distance(0, 0, 0, Math.toRadians(0.01)) / 20) + 1;
        check("long-segment-20m", expected, count(g, false));

        ScenarioState.clearData(); ScenarioState.processLMCP(task(WavelengthBand.EO, 0.01), 0);
        AnalysisManager manager = new AnalysisManager();
        manager.addedToApplication(new Context(), XmlReader.readDocument("<Plugin><Analysis><PluginList>"
            + "<Plugin>avtas.amase.analysis.SearchTaskAnalysis</Plugin></PluginList>"
            + "<SearchTaskAnalysis><GridResolution>10</GridResolution></SearchTaskAnalysis></Analysis></Plugin>"), new String[0]);
        try {
            manager.getAnalysisReportXML(); check("analysis-without-window-dependency", 1, 1);
            SearchTaskAnalysis analysis = (SearchTaskAnalysis)manager.clientList.get(0);
            check("configured-resolution-forwarded", (long)(NavUtils.distance(0, 0, 0, Math.toRadians(0.01)) / 10) + 1,
                  count(analysis.graphicMap.get(1000L), false));
            manager.getAnalysisReportXML(); check("incremental-report-not-duplicated", 1, analysis.graphicMap.size());
        } catch (java.awt.HeadlessException error) { check("analysis-without-window-dependency", 1, 0); }
        results.setAttribute("failures", String.valueOf(failures));
        Files.writeString(Path.of(args[0]), results.toXML(), StandardCharsets.UTF_8);
        System.out.println("Coverage fixtures: failures=" + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
