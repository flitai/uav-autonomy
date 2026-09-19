package validation.g3;

import afrl.cmasi.AirVehicleState;
import afrl.cmasi.SimulationStatusType;
import avtas.amase.AmasePlugin;
import avtas.amase.util.SimTimer;
import avtas.app.Context;
import avtas.lmcp.LMCPObject;
import avtas.lmcp.LMCPFactory;
import avtas.xml.Element;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Base64;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import javax.swing.Timer;

/** Run-local controls and evidence only. No synthetic state or mission commands. */
public final class StartupProbe extends AmasePlugin {
    private final Path directory = Path.of(System.getProperty("g3.integration.directory"));
    private final String fault = System.getProperty("g3.integration.testFault", "");
    private final Set<Long> observedEntities = ConcurrentHashMap.newKeySet();
    private PrintWriter writer;
    private Context context;
    private long sequence;
    private boolean closed, started, paused, frozen;

    private static String quote(Object value) {
        return "\"" + String.valueOf(value).replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    private synchronized void log(String kind, String fields) {
        if (closed) return;
        writer.println("{\"kind\":" + quote(kind) + ",\"wallTime\":" + quote(Instant.now())
            + ",\"simTimeSeconds\":" + quote(SimTimer.getTime()) + fields + "}");
        writer.flush();
        if (writer.checkError()) throw new IllegalStateException("Cannot save G3 evidence");
    }

    @Override public void addedToApplication(Context c, Element xml, String[] args) {
        context = c;
        try {
            writer = new PrintWriter(Files.newBufferedWriter(directory.resolve("events.jsonl"), StandardCharsets.UTF_8));
        } catch (Exception e) { throw new IllegalStateException(e); }
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            synchronized (StartupProbe.this) {
                log("shutdown", "");
                closed = true;
                writer.close();
            }
        }, "g3-startup-evidence"));
    }

    @Override public void initializeComplete() {
        SimTimer.pause();
        log("initialized-paused", ",\"amaseSource\":" + quote(AmasePlugin.class.getProtectionDomain().getCodeSource().getLocation())
            + ",\"lmcpSource\":" + quote(LMCPFactory.class.getProtectionDomain().getCodeSource().getLocation()));
        new Timer(50, e -> {
            if (Files.exists(directory.resolve("request-shutdown")) && !fault.equals("shutdown-timeout")) {
                ((Timer) e.getSource()).stop();
                SimTimer.pause();
                log("shutdown-request", "");
                context.requestShutdown();
            } else if (!started && Files.exists(directory.resolve("request-start"))) {
                started = true;
                log("start-request", "");
                SimTimer.setRealtimeMultiple(1);
                SimTimer.go();
            } else if (!started && SimTimer.getStatus() == SimulationStatusType.Running) {
                SimTimer.pause();
                log("unexpected-start", "");
            } else if (started && !paused && Files.exists(directory.resolve("request-pause"))) {
                SimTimer.pause();
                paused = true;
                log("paused", "");
            } else if (fault.equals("static-state") && !frozen && observedEntities.size() == 2) {
                SimTimer.pause();
                frozen = true;
                log("test-frozen", "");
            }
        }).start();
    }

    @Override public synchronized void eventOccurred(Object event) {
        if (event instanceof AirVehicleState) observedEntities.add(((AirVehicleState) event).getID());
        if (event instanceof LMCPObject) {
            LMCPObject object = (LMCPObject) event;
            String xml = Base64.getEncoder().encodeToString(object.toXML("").getBytes(StandardCharsets.UTF_8));
            log("message", ",\"sequence\":" + quote(++sequence) + ",\"type\":" + quote(object.getClass().getName())
                + ",\"xmlBase64\":" + quote(xml));
        }
    }
}
