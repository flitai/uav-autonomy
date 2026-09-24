package validation.g6;

import afrl.cmasi.SimulationStatusType;
import avtas.amase.AmasePlugin;
import avtas.amase.util.SimTimer;
import avtas.app.Context;
import avtas.xml.Element;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import java.util.Comparator;
import javax.swing.Timer;

/** Executes one bounded, run-local control request at a time inside AMASE. */
public final class ControlProbe extends AmasePlugin {
    private final Path directory = Path.of(System.getProperty("g6.control.directory"));
    private final Path requests = directory.resolve("requests");
    private final Path results = directory.resolve("results");
    private Timer poller;

    @Override public void addedToApplication(Context context, Element xml, String[] args) {
        try {
            Files.createDirectories(requests);
            Files.createDirectories(results);
        } catch (Exception error) { throw new IllegalStateException("Cannot initialize G6 control directory", error); }
    }

    @Override public void initializeComplete() {
        poller = new Timer(100, event -> poll());
        poller.start();
    }

    private void poll() {
        try (java.util.stream.Stream<Path> entries = Files.list(requests)) {
            Path[] files = entries.filter(path -> path.getFileName().toString().matches("[0-9]{12}\\.request"))
                .sorted(Comparator.comparing(path -> path.getFileName().toString())).limit(2).toArray(Path[]::new);
            if (files.length != 1) return; // a backlog is ambiguous; the controller must resolve it
            Path path = files[0];
            String id = path.getFileName().toString().substring(0, 12);
            Path result = results.resolve(id + ".json");
            if (Files.exists(result)) { Files.delete(path); return; }
            if (Files.size(path) > 64) throw new IllegalArgumentException("Control request exceeds 64 bytes");
            String[] lines = Files.readString(path, StandardCharsets.US_ASCII).split("\\r?\\n", -1);
            String action = lines.length > 0 ? lines[0] : "";
            String argument = lines.length > 1 ? lines[1] : "";
            String outcome = "applied";
            if (lines.length > 3 || lines.length == 3 && !lines[2].isEmpty()) outcome = "invalid";
            else if (action.equals("pause") && argument.isEmpty()) {
                if (SimTimer.getStatus() == SimulationStatusType.Running) SimTimer.pause();
                else if (SimTimer.getStatus() != SimulationStatusType.Paused) outcome = "rejected";
            }
            else if (action.equals("resume") && argument.isEmpty()) {
                if (SimTimer.getStatus() == SimulationStatusType.Paused) SimTimer.go();
                else if (SimTimer.getStatus() != SimulationStatusType.Running) outcome = "rejected";
            }
            else if (action.equals("rate") && Arrays.asList("0.25", "0.5", "1", "2", "5", "10").contains(argument))
                SimTimer.setRealtimeMultiple(Double.parseDouble(argument));
            else outcome = "invalid";
            String body = "{\"id\":\"" + id + "\",\"action\":\"" + action.replaceAll("[^a-z]", "")
                + "\",\"outcome\":\"" + outcome + "\",\"simulationTimeMs\":\""
                + (long)(SimTimer.getTime() * 1000) + "\",\"state\":" + SimTimer.getStatus().getValue()
                + ",\"realTimeMultiple\":" + SimTimer.getRealtimeMultiple() + "}";
            Path temporary = results.resolve(id + ".tmp");
            Files.writeString(temporary, body, StandardCharsets.UTF_8);
            Files.move(temporary, result, StandardCopyOption.ATOMIC_MOVE);
            Files.delete(path);
        } catch (Exception error) {
            // The controller times out and preserves the request as uncertain.
            System.err.println("G6 control request failed: " + error);
        }
    }

    @Override public void shutdown() {
        if (poller != null) poller.stop();
    }
}
