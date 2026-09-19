package validation.g3;

import afrl.cmasi.MissionCommand;
import avtas.amase.entity.EntityModule;
import avtas.amase.util.SimTimer;
import avtas.xml.Element;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;

/** Read-only entity module: observes the autopilot after WaypointFollower steps.
 * Never calls getState(), changes properties, or emits application/model events.
 */
public final class ExecutionProbe extends EntityModule {
    private PrintWriter writer;
    private long command = -1, lastCommand = -1, lastWaypoint = -1, sequence;
    private double lastTime = -1;

    @Override public void initialize(Element xml) {
        try {
            Path directory = Path.of(System.getProperty("g3.integration.directory"));
            writer = new PrintWriter(Files.newBufferedWriter(directory.resolve("execution-" + getModel().getID() + ".jsonl"), StandardCharsets.UTF_8));
        } catch (Exception error) { throw new IllegalStateException(error); }
        Runtime.getRuntime().addShutdownHook(new Thread(() -> { synchronized (ExecutionProbe.this) { writer.close(); } }, "g3-execution-close"));
    }

    @Override public synchronized void modelEventOccurred(Object event) {
        if (event instanceof MissionCommand && !((MissionCommand) event).getWaypointList().isEmpty()) {
            command = ((MissionCommand) event).getCommandID();
            // The first target can be consumed on the very next simulation step.
            // Observe the real applied properties here as well as after steps.
            record("command-applied", SimTimer.getTime());
        }
    }

    @Override public synchronized void step(double dt, double simTime) {
        long waypoint = data.autopilotCommands.currentWaypoint.asInteger();
        if (command == lastCommand && waypoint == lastWaypoint && simTime - lastTime < 0.2) return;
        record("step", simTime);
        lastCommand = command; lastWaypoint = waypoint; lastTime = simTime;
    }

    private void record(String sampleKind, double simTime) {
        long waypoint = data.autopilotCommands.currentWaypoint.asInteger();
        writer.println("{\"kind\":\"navigation\",\"sequence\":\"" + (++sequence)
            + "\",\"sampleKind\":\"" + sampleKind
            + "\",\"entityId\":\"" + getModel().getID() + "\",\"commandId\":\"" + command
            + "\",\"waypoint\":\"" + waypoint + "\",\"waypointReached\":\"" + data.autopilotCommands.waypointReached.asInteger()
            + "\",\"mode\":\"" + data.autopilotCommands.navMode.getValue() + "\",\"simTimeSeconds\":\"" + simTime
            + "\",\"wallTime\":\"" + Instant.now() + "\",\"position\":[" + Math.toDegrees(data.lat.asDouble())
            + "," + Math.toDegrees(data.lon.asDouble()) + "," + data.alt.asDouble() + "]}");
        writer.flush();
        if (writer.checkError()) throw new IllegalStateException("Cannot save execution evidence");
    }
}
