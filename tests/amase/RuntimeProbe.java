package validation;

import afrl.cmasi.AirVehicleState;
import afrl.cmasi.SessionStatus;
import avtas.amase.AmasePlugin;
import avtas.amase.util.SimTimer;
import avtas.app.Context;
import avtas.terrain.TerrainService;
import avtas.xml.Element;
import java.awt.GraphicsEnvironment;
import java.awt.Window;
import java.awt.image.BufferedImage;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import javax.imageio.ImageIO;
import javax.swing.SwingUtilities;
import javax.swing.Timer;

/** Test-only observer. It reads real application events, never synthesizes messages. */
public final class RuntimeProbe extends AmasePlugin {
    private final Path directory = Path.of(System.getProperty("amase.probe.directory"));
    private final boolean checking = Boolean.getBoolean("amase.probe.validate");
    private final boolean headless = GraphicsEnvironment.isHeadless();
    private PrintWriter writer;
    private boolean pauseScheduled;
    private boolean closed;
    private Context context;

    private static String quote(Object value) {
        String s = String.valueOf(value);
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }

    private synchronized void log(String kind, String fields) {
        if (closed) return;
        writer.println("{\"kind\":" + quote(kind) + ",\"wallTime\":" + quote(Instant.now()) + fields + "}");
        writer.flush();
        if (writer.checkError()) throw new IllegalStateException("Cannot write probe evidence");
    }

    @Override public void addedToApplication(Context c, Element xml, String[] args) {
        context = c;
        try {
            writer = new PrintWriter(Files.newBufferedWriter(directory.resolve("events.jsonl"), StandardCharsets.UTF_8));
        } catch (Exception e) { throw new IllegalStateException(e); }
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            synchronized (RuntimeProbe.this) {
                log("shutdown", ",\"simTime\":" + SimTimer.getTime());
                closed = true;
                writer.close();
            }
        }, "amase-evidence-flush"));
    }

    @Override public void initializeComplete() {
        SwingUtilities.invokeLater(() -> {
            StringBuilder plugins = new StringBuilder();
            for (Object object : context.getObjects()) {
                if (plugins.length() > 0) plugins.append(',');
                plugins.append(quote(object.getClass().getName()));
            }
            log("initialized", ",\"headless\":" + headless + ",\"visibleWindows\":" + visibleWindows()
                + ",\"plugins\":[" + plugins + "],\"lmcpSource\":"
                + quote(AirVehicleState.class.getProtectionDomain().getCodeSource().getLocation().toExternalForm())
                + ",\"amaseSource\":" + quote(SimTimer.class.getProtectionDomain().getCodeSource().getLocation().toExternalForm())
                + ",\"uxtaskVersion\":" + new uxas.messages.task.TaskActive().getLMCPSeriesVersion()
                + ",\"terrainElevation\":" + TerrainService.getElevation(45.323, -120.9645));
            if (!headless && checking) {
                SimTimer.setRealtimeMultiple(Double.parseDouble(System.getProperty("amase.probe.simRate", "1")));
                SimTimer.go();
            }
            new Timer(250, evt -> {
                if (Files.exists(directory.resolve("request-shutdown"))) {
                    ((Timer) evt.getSource()).stop();
                    log("shutdown-request", "");
                    context.requestShutdown();
                }
            }).start();
        });
    }

    private int visibleWindows() {
        int count = 0;
        for (Window window : Window.getWindows()) if (window.isVisible()) count++;
        return count;
    }

    @Override public void eventOccurred(Object event) {
        if (event instanceof AirVehicleState) {
            AirVehicleState s = (AirVehicleState) event;
            if (s.getID() == 400 || s.getID() == 500) {
                log("entity", ",\"id\":" + quote(s.getID()) + ",\"timeMs\":" + quote(s.getTime())
                    + ",\"latitude\":" + s.getLocation().getLatitude() + ",\"longitude\":" + s.getLocation().getLongitude()
                    + ",\"altitude\":" + s.getLocation().getAltitude());
            }
        } else if (event instanceof SessionStatus) {
            SessionStatus s = (SessionStatus) event;
            log("session", ",\"timeMs\":" + quote(s.getScenarioTime()) + ",\"state\":" + quote(s.getState()));
            if (!headless && checking && !pauseScheduled && s.getScenarioTime() >= 20000) {
                pauseScheduled = true;
                SwingUtilities.invokeLater(() -> {
                    SimTimer.pause();
                    Timer delayed = new Timer(700, evt -> {
                        log("gui-ready", ",\"simTime\":" + SimTimer.getTime() + ",\"visibleWindows\":" + visibleWindows());
                        for (Window window : Window.getWindows()) {
                            if (window.isVisible() && window.getClass().getName().equals("avtas.amase.window.AmaseWindow")) {
                                try {
                                    BufferedImage image = new BufferedImage(window.getWidth(), window.getHeight(), BufferedImage.TYPE_INT_RGB);
                                    java.awt.Graphics2D graphics = image.createGraphics();
                                    window.printAll(graphics);
                                    graphics.dispose();
                                    ImageIO.write(image, "png", directory.resolve("gui.png").toFile());
                                } catch (Exception error) { throw new IllegalStateException(error); }
                            }
                        }
                    });
                    delayed.setRepeats(false);
                    delayed.start();
                });
            }
        }
    }
}
