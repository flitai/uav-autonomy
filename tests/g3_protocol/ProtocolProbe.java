package validation.g3;

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
import javax.swing.Timer;

/** Observes the real AMASE event bus. Does not inject states or planning commands. */
public final class ProtocolProbe extends AmasePlugin {
    private final Path directory = Path.of(System.getProperty("g3.protocol.directory"));
    private PrintWriter writer;
    private Context context;
    private long sequence;
    private boolean closed;
    private boolean started;

    private static String quote(Object o) {
        return "\"" + String.valueOf(o).replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    private synchronized void log(String kind, String fields) {
        if (closed) return;
        writer.println("{\"kind\":" + quote(kind) + ",\"wallTime\":" + quote(Instant.now()) + fields + "}");
        writer.flush();
        if (writer.checkError()) throw new IllegalStateException("Cannot save protocol events");
    }

    @Override public void addedToApplication(Context c, Element xml, String[] args) {
        context = c;
        try {
            writer = new PrintWriter(Files.newBufferedWriter(directory.resolve("events.jsonl"), StandardCharsets.UTF_8));
        } catch (Exception e) { throw new IllegalStateException(e); }
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            synchronized (ProtocolProbe.this) {
                log("shutdown", "");
                closed = true;
                writer.close();
            }
        }, "g3-protocol-evidence"));
    }

    @Override public void initializeComplete() {
        log("initialized", ",\"amaseSource\":" + quote(AmasePlugin.class.getProtectionDomain().getCodeSource().getLocation())
            + ",\"lmcpSource\":" + quote(LMCPFactory.class.getProtectionDomain().getCodeSource().getLocation()));
        new Timer(100, e -> {
            if (Files.exists(directory.resolve("request-shutdown"))) {
                ((Timer) e.getSource()).stop();
                log("shutdown-request", "");
                context.requestShutdown();
            } else if (!started && Files.exists(directory.resolve("request-start"))) {
                started = true;
                log("start-request", ",\"simTimeSeconds\":" + quote(SimTimer.getTime()));
                SimTimer.setRealtimeMultiple(1);
                SimTimer.go();
            }
        }).start();
    }

    @Override public synchronized void eventOccurred(Object event) {
        if (event instanceof LMCPObject) {
            LMCPObject object = (LMCPObject) event;
            String xml = Base64.getEncoder().encodeToString(object.toXML("").getBytes(StandardCharsets.UTF_8));
            log("message", ",\"sequence\":" + quote(++sequence) + ",\"type\":" + quote(object.getClass().getName())
                + ",\"xmlBase64\":" + quote(xml));
        }
    }
}
