package avtas.amase.analysis;

import afrl.cmasi.*;
import avtas.util.NavUtils;
import avtas.xml.Element;
import java.awt.geom.Path2D;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/** Small independent geometry/time samples; never a substitute for real flight. */
public final class SearchChecks {
    private static int failures;
    private static final Element results = new Element("MixedSearchChecks");
    static void check(String name, double expected, double actual) {
        boolean passed = Double.isFinite(actual) && Math.abs(expected-actual)<1e-6;
        Element e = new Element("Check"); e.setAttribute("name",name);
        e.setAttribute("expected",Double.toString(expected)); e.setAttribute("actual",Double.toString(actual));
        e.setAttribute("passed",Boolean.toString(passed)); results.add(e);
        if (!passed) failures++;
    }
    static Location3D location(double latitude, double longitude) {
        Location3D p=new Location3D(); p.setLatitude(latitude); p.setLongitude(longitude); return p;
    }
    static void search(SearchTask task, WavelengthBand band) {
        task.setTaskID(2000); task.setGroundSampleDistance(1); task.setDwellTime(0);
        task.getDesiredWavelengthBands().clear(); task.getDesiredWavelengthBands().add(band);
    }
    static PointSearchHighlight point(WavelengthBand band) {
        PointSearchTask task=new PointSearchTask(); search(task,band);
        task.setSearchLocation(location(45,0)); return new PointSearchHighlight(task);
    }
    static AirVehicleState state(long time) {
        AirVehicleState s=new AirVehicleState(); s.setID(400); s.setTime(time); return s;
    }
    static class Camera extends CameraModel {
        boolean inside=true; double gsd=.5;
        Camera(long id) {
            super(new AirVehicleConfiguration(),new CameraConfiguration(),new GimbalConfiguration());
            getCameraConfig().setSupportedWavelengthBand(WavelengthBand.EO);
            getCameraConfig().setPayloadID(id); setCameraConfig(getCameraConfig());
        }
        @Override public Path2D getFootprint(AirVehicleState s) {
            Path2D p=new Path2D.Double(); double west=inside ? -1 : 10;
            p.moveTo(west,44); p.lineTo(west+2,44); p.lineTo(west+2,46); p.lineTo(west,46); p.closePath(); return p;
        }
        @Override public double computeGSD(AirVehicleState s,SearchGraphic.SearchPixel p,double altitude) { return gsd; }
    }
    static double seen(PointSearchHighlight g) { return g.getPixels()[0][0].totalTimeSeen; }
    static int cells(SearchGraphic g, boolean seen) {
        int count=0; for(SearchGraphic.SearchPixel[] row:g.getPixels()) for(SearchGraphic.SearchPixel p:row)
            if(p!=null && (!seen || p.seen)) count++;
        return count;
    }
    public static void main(String[] args) throws Exception {
        Camera camera=new Camera(1);
        for(WavelengthBand band:new WavelengthBand[]{WavelengthBand.EO,WavelengthBand.AllAny,WavelengthBand.LWIR}) {
            PointSearchHighlight g=point(band); g.processSensor(state(0),camera,100); g.processSensor(state(500),camera,100);
            check("point-band-"+band,band==WavelengthBand.LWIR?0:500,seen(g));
        }
        PointSearchHighlight g=point(WavelengthBand.EO);
        for(long time:new long[]{0,500,1000}) g.processSensor(state(time),camera,100);
        check("point-zero-dwell-observation-ms",1000,seen(g));
        g.processSensor(state(1000),camera,100); g.processSensor(state(500),camera,100);
        check("point-duplicate-and-old-time",1000,seen(g));
        camera.inside=false; g.processSensor(state(1500),camera,100);
        camera.inside=true; g.processSensor(state(2000),camera,100); g.processSensor(state(2500),camera,100);
        check("point-unobserved-gap-excluded",1500,seen(g));
        g.processSensor(state(10000),camera,100); g.processSensor(state(10500),camera,100);
        check("point-missing-sample-gap-excluded",2000,seen(g));
        Camera second=new Camera(2); g.processSensor(state(10000),second,100); g.processSensor(state(10500),second,100);
        check("point-simultaneous-cameras-union",2000,seen(g));
        camera.gsd=2; g.processSensor(state(11000),camera,100); camera.gsd=.5;
        g.processSensor(state(11500),camera,100); g.processSensor(state(12000),camera,100);
        check("point-gsd-gap-excluded",2500,seen(g));
        g.initialize(); check("point-reset-time",0,seen(g));
        g.processSensor(state(12500),camera,100); check("point-reset-history",0,seen(g));
        PointSearchHighlight dwell=point(WavelengthBand.EO); dwell.getTask().setDwellTime(1000);
        dwell.processSensor(state(0),camera,100); dwell.processSensor(state(500),camera,100);
        check("point-dwell-before-threshold",0,dwell.getPixels()[0][0].seen?1:0);
        dwell.processSensor(state(1000),camera,100); check("point-dwell-threshold",1,dwell.getPixels()[0][0].seen?1:0);
        dwell.processSensor(state(1500),camera,100); check("point-continues-after-dwell",1500,seen(dwell));
        dwell.processSensor(state(1250),second,100); dwell.processSensor(state(1750),second,100);
        check("point-partial-camera-overlap",1750,seen(dwell));
        SearchTaskAnalysis analysis=new SearchTaskAnalysis();
        g.getPixels()[0][0].totalTimeSeen=750; analysis.graphicMap.put(2000L,g);
        Element report=analysis.getAnalysisReportXML();
        check("point-report-seconds",.75,Double.parseDouble(report.getChild("SearchPoint").getChild("TimeSeenSec").getText()));

        double dlat=Math.toDegrees(20/NavUtils.EARTH_EQ_RADIUS_M), dlon=dlat/Math.cos(Math.toRadians(45));
        Polygon polygon=new Polygon();
        polygon.getBoundaryPoints().add(location(45+1.5*dlat,-2*dlon));
        polygon.getBoundaryPoints().add(location(45+1.5*dlat, 2*dlon));
        polygon.getBoundaryPoints().add(location(45-1.5*dlat, 2*dlon));
        polygon.getBoundaryPoints().add(location(45-1.5*dlat,-2*dlon));
        for(WavelengthBand band:new WavelengthBand[]{WavelengthBand.EO,WavelengthBand.AllAny,WavelengthBand.LWIR}) {
            AreaSearchTask task=new AreaSearchTask(); search(task,band); task.setSearchArea(polygon);
            AreaSearchHighlight area=new AreaSearchHighlight(20,task);
            check("area-manual-four-by-three-"+band,12,cells(area,false));
            check("area-northwest-center-"+band,1,area.getPixels()[0][0]!=null?1:0);
            area.processSensor(state(500),camera,100);
            check("area-band-"+band,band==WavelengthBand.LWIR?0:12,cells(area,true));
            area.initialize(); check("area-reset-"+band,0,cells(area,true));
        }
        AreaSearchTask invalid=new AreaSearchTask(); search(invalid,WavelengthBand.EO); invalid.setSearchArea(polygon);
        for(double resolution:new double[]{0,Double.NaN,0.001}) {
            try { new AreaSearchHighlight(resolution,invalid); check("area-invalid-grid-"+resolution,1,0); }
            catch(IllegalArgumentException expected) { check("area-invalid-grid-"+resolution,1,1); }
        }
        results.setAttribute("failures",Integer.toString(failures));
        Files.writeString(Path.of(args[0]),results.toXML(),StandardCharsets.UTF_8);
        System.out.println("Mixed search fixture failures="+failures); System.exit(failures==0?0:1);
    }
}
