package avtas.amase.entity.modules;

import afrl.cmasi.*;
import avtas.amase.entity.EntityData;
import avtas.xml.Element;
import java.nio.file.Files;
import java.nio.file.Path;

/** Test the actual follower boundary, without changing a flight scenario. */
public final class TerminalChecks {
    private static final Element report = new Element("TerminalChecks");
    private static int failures;
    private static final class FixtureFollower extends WaypointFollower {
        FixtureFollower() { data = new EntityData(); }
    }
    private static void check(String name, long expected, long actual) {
        Element e = new Element("Check"); e.setAttribute("name", name);
        e.setAttribute("expected", Long.toString(expected)); e.setAttribute("actual", Long.toString(actual));
        e.setAttribute("passed", Boolean.toString(expected == actual)); report.add(e);
        if (expected != actual) failures++;
    }
    private static WaypointFollower follower(boolean taskFreeSuccessor, boolean colocated) {
        WaypointFollower follower = new FixtureFollower(); follower.initialize(new Element("Module"));
        EntityData data = follower.getData();
        data.lat.setValue(Math.toRadians(0.0001)); data.lon.setValue(0.0); data.alt.setValue(700.0);
        data.u.setValue(22.0); data.psi.setValue(0.0); data.autopilotCommands.maxBank.setValue(Math.toRadians(20));
        Waypoint last = new Waypoint(); last.setNumber(73); last.setNextWaypoint(74); last.setLatitude(0.001);
        last.setLongitude(0); last.setAltitude(700); last.setSpeed(22); last.setTurnType(TurnType.TurnShort);
        last.getAssociatedTasks().add(1000L);
        Waypoint end = last.clone(); end.setNumber(74); end.setNextWaypoint(74);
        if (taskFreeSuccessor) end.getAssociatedTasks().clear();
        if (!colocated) end.setLatitude(0.002);
        MissionCommand mission = new MissionCommand(); mission.setFirstWaypoint(73); mission.setVehicleID(400);
        mission.getWaypointList().add(last); mission.getWaypointList().add(end);
        follower.modelEventOccurred(mission); return follower;
    }
    public static void main(String[] args) throws Exception {
        WaypointFollower f = follower(true, true); f.step(0.03, 1);
        check("terminal-not-consumed-before-arrival", 73, f.getData().autopilotCommands.currentWaypoint.asInteger());
        AirVehicleState state = new AirVehicleState(); f.modelEventOccurred(state);
        check("task-remains-active-before-arrival", 1, state.getAssociatedTasks().size());
        f.getData().lat.setValue(Math.toRadians(0.0011)); f.step(0.03, 2);
        check("terminal-consumed-after-passage", 74, f.getData().autopilotCommands.currentWaypoint.asInteger());
        check("native-arrival-record", 73, f.getData().autopilotCommands.waypointReached.asInteger());
        f.modelEventOccurred(state); check("task-cleared-after-passage", 0, state.getAssociatedTasks().size());
        f = follower(false, true); f.step(0.03, 1);
        check("ordinary-turn-short-preserved", 74, f.getData().autopilotCommands.currentWaypoint.asInteger());
        report.setAttribute("failures", Integer.toString(failures));
        Files.writeString(Path.of(args[0]), report.toXML());
        System.out.println("Terminal fixtures: failures=" + failures); System.exit(failures == 0 ? 0 : 1);
    }
}
