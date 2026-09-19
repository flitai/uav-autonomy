package avtas.amase.analysis;

import avtas.amase.scenario.ScenarioState;
import avtas.app.Context;
import avtas.lmcp.LMCPObject;
import avtas.lmcp.LMCPXMLReader;
import avtas.xml.Element;
import avtas.xml.XmlReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;

/** Replay the same recorded events through the original AnalysisManager API. */
public final class AnalysisReplay {
    public static void main(String[] args) throws Exception {
        ScenarioState.clearData();
        try (java.io.BufferedReader reader = Files.newBufferedReader(Path.of(args[0]), StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                String[] fields = line.split("\t", 2);
                LMCPObject event = LMCPXMLReader.readXML(new String(Base64.getDecoder().decode(fields[1]), StandardCharsets.UTF_8));
                if (event == null) throw new IllegalArgumentException("Undecodable event");
                ScenarioState.processLMCP(event, Double.parseDouble(fields[0]));
            }
        }
        Element plugins = XmlReader.readDocument(Files.readString(Path.of(args[1]), StandardCharsets.UTF_8));
        Element configuration = null;
        for (Element plugin : plugins.getChildElements())
            if ("avtas.amase.analysis.AnalysisManager".equals(plugin.getAttribute("Class"))) configuration = plugin;
        if (configuration == null) throw new IllegalArgumentException("AnalysisManager missing");
        AnalysisManager manager = new AnalysisManager();
        manager.addedToApplication(new Context(), configuration, new String[0]);
        Path out = Path.of(args[2]); Files.createDirectories(out);
        Files.writeString(out.resolve("analysis.xml"), manager.getAnalysisReportXML().toXML(), StandardCharsets.UTF_8);
        SearchTaskAnalysis search = null;
        for (AnalysisClient client : manager.clientList) if (client instanceof SearchTaskAnalysis) search = (SearchTaskAnalysis)client;
        if (search == null) throw new IllegalStateException("Search analysis missing");
        // Independent extraction of native pixels also works against the pre-fix JAR.
        try (java.io.BufferedWriter writer = Files.newBufferedWriter(out.resolve("pixels.csv"), StandardCharsets.UTF_8)) {
            writer.write("task,row,column,latitude,longitude,seen\n");
            for (Long id : new java.util.TreeSet<>(search.graphicMap.keySet())) {
                SearchGraphic.SearchPixel[][] pixels = search.graphicMap.get(id).getPixels();
                for (int i = 0; i < pixels.length; i++) for (int j = 0; j < pixels[i].length; j++) {
                    SearchGraphic.SearchPixel p = pixels[i][j];
                    if (p != null) writer.write(id + "," + i + "," + j + "," + p.lat + "," + p.lon + "," + p.seen + "\n");
                }
            }
        }
        Files.writeString(out.resolve("incremental.xml"), manager.getAnalysisReportXML().toXML(), StandardCharsets.UTF_8);
        manager.resetAnalysis();
        Files.writeString(out.resolve("reset-replay.xml"), manager.getAnalysisReportXML().toXML(), StandardCharsets.UTF_8);
        System.out.println("Analysis replay: " + out + "; headless=" + java.awt.GraphicsEnvironment.isHeadless());
        System.exit(0);
    }
}
