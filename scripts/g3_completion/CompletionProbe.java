package validation.g3;

import avtas.amase.AmasePlugin;
import avtas.amase.analysis.AnalysisClient;
import avtas.amase.analysis.AnalysisManager;
import avtas.amase.analysis.SearchTaskAnalysis;
import avtas.amase.scenario.ScenarioState;
import avtas.amase.util.SimTimer;
import avtas.app.Context;
import avtas.xml.Element;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import javax.swing.Timer;

/** Export the actual application's analysis after the controller pauses it. */
public final class CompletionProbe extends AmasePlugin {
    private Context context;
    private final Path directory = Path.of(System.getProperty("g3.integration.directory"));
    @Override public void addedToApplication(Context c, Element xml, String[] args) { context = c; }
    @Override public void initializeComplete() {
        new Timer(100, e -> {
            if (!Files.exists(directory.resolve("request-analysis"))) return;
            ((Timer)e.getSource()).stop();
            try {
                if (SimTimer.getStatus() == afrl.cmasi.SimulationStatusType.Running)
                    throw new IllegalStateException("Analysis requires a paused simulation");
                Object[] managers = context.getObjects(AnalysisManager.class.getName());
                if (managers.length != 1) throw new IllegalStateException("Expected one AnalysisManager");
                AnalysisManager manager = (AnalysisManager)managers[0];
                Files.writeString(directory.resolve("analysis.xml"), manager.getAnalysisReportXML().toXML(), StandardCharsets.UTF_8);
                int searches = 0;
                for (AnalysisClient client : manager.getAnalysisClients()) if (client instanceof SearchTaskAnalysis) {
                    searches++;
                    Files.writeString(directory.resolve("coverage-cells.xml"),
                        ((SearchTaskAnalysis)client).getCoverageCellsXML().toXML(), StandardCharsets.UTF_8);
                }
                if (searches != 1) throw new IllegalStateException("Expected one SearchTaskAnalysis");
                try (java.io.BufferedWriter writer = Files.newBufferedWriter(directory.resolve("analysis-events.tsv"), StandardCharsets.UTF_8)) {
                    for (ScenarioState.EventWrapper event : new ArrayList<>(ScenarioState.getEventList())) {
                        writer.write(Double.toString(event.time)); writer.write('\t');
                        writer.write(Base64.getEncoder().encodeToString(event.event.toXML("").getBytes(StandardCharsets.UTF_8)));
                        writer.newLine();
                    }
                }
                Files.writeString(directory.resolve("analysis-done"), Double.toString(SimTimer.getTime()), StandardCharsets.UTF_8);
            } catch (Exception error) {
                try { Files.writeString(directory.resolve("analysis-error"), error.toString(), StandardCharsets.UTF_8); }
                catch (Exception ignored) { throw new IllegalStateException(error); }
            }
        }).start();
    }
}
