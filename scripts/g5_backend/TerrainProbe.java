package avtas.terrain;

import avtas.amase.AmasePlugin;
import avtas.amase.util.SimTimer;
import avtas.app.Context;
import avtas.xml.Element;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/** Run-local qualification wrapper. Every valid query delegates to the formal
 * DTEDCache/DTEDTile. No height, flight, camera or analysis algorithm is replaced.
 * The cache identity and bounded call samples are recorded for independent audit.
 */
public final class TerrainProbe extends AmasePlugin {
    @Override public void addedToApplication(Context context, Element xml, String[] args) {
        try {
            Path directory = Path.of(System.getProperty("g3.integration.directory"));
            QualifiedCache cache = new QualifiedCache(directory);
            cache.addDirectory(directory.resolve("data/g5-dted").toFile());
            for (int lon = -122; lon < -120; lon++) {
                DTEDTile tile = cache.getTile(45.5, lon + 0.5);
                if (tile == null || tile.numlats != 1201 || tile.numlons != 1201 || tile.level != 1)
                    throw new IllegalStateException("Missing qualified DTED tile");
                for (short[] column : tile.getAllElevations()) for (short height : column)
                    if (height < 0) throw new IllegalStateException("Formal DTED reader is not qualified for negative heights");
            }
            TerrainService.cache = cache;
            Files.writeString(directory.resolve("terrain-loaded.json"), "{\"status\":\"passed\",\"tiles\":2,"
                + "\"tileSource\":\"" + DTEDTile.class.getProtectionDomain().getCodeSource().getLocation().toString()
                + "\",\"cacheSource\":\"" + DTEDCache.class.getProtectionDomain().getCodeSource().getLocation().toString()
                + "\",\"metadataSpacingDefectUnchanged\":true,\"negativeHeightsAccepted\":false}", StandardCharsets.UTF_8);
            Runtime.getRuntime().addShutdownHook(new Thread(cache::finish, "g5-terrain-evidence"));
        } catch (Exception error) { throw new IllegalStateException(error); }
    }

    static final class QualifiedCache extends DTEDCache {
        private final Path directory;
        private final PrintWriter samples, rays;
        private final Map<String, Long> counts = new LinkedHashMap<>();
        private long queries, intercepts, initializationPlaceholders, sampleCount, rayCount;
        private double minimum = Double.POSITIVE_INFINITY, maximum = Double.NEGATIVE_INFINITY;
        QualifiedCache(Path directory) throws Exception {
            this.directory = directory;
            samples = new PrintWriter(Files.newBufferedWriter(directory.resolve("terrain-queries.jsonl"), StandardCharsets.UTF_8));
            rays = new PrintWriter(Files.newBufferedWriter(directory.resolve("terrain-rays.jsonl"), StandardCharsets.UTF_8));
        }
        private IllegalStateException failure(String message) {
            try { Files.writeString(directory.resolve("terrain-error"), message, StandardCharsets.UTF_8); }
            catch (Exception error) { return new IllegalStateException(error); }
            return new IllegalStateException(message);
        }
        private boolean inside(double lat, double lon) {
            return Double.isFinite(lat) && Double.isFinite(lon) && lat >= 45 && lat < 46 && lon >= -122 && lon < -120;
        }
        private String caller() {
            for (StackTraceElement entry : Thread.currentThread().getStackTrace()) {
                String name = entry.getClassName();
                if (name.startsWith("avtas.amase.")) return name + "." + entry.getMethodName();
            }
            return "other";
        }
        @Override public synchronized short getElevation(double lat, double lon) {
            // Existing scenario creates configuration at t=1 and supplies initial
            // state at t=1.4. Such (0,0) placeholders are outside flight qualification.
            if (lat == 0 && lon == 0 && SimTimer.getTime() <= 1.4) {
                initializationPlaceholders++;
                return super.getElevation(lat, lon);
            }
            if (!inside(lat, lon) || super.getTile(lat, lon) == null)
                throw failure("Unqualified terrain query: " + lat + "," + lon);
            short height = super.getElevation(lat, lon);
            if (height < 0) throw failure("Negative DTED not qualified");
            queries++; minimum = Math.min(minimum, height); maximum = Math.max(maximum, height);
            String caller = caller(); long count = counts.getOrDefault(caller, 0L) + 1; counts.put(caller, count);
            if (sampleCount < 1024 && (count <= 8 || count % 1024 == 0)) {
                sampleCount++;
                samples.println("{\"caller\":\"" + caller + "\",\"latitude\":" + lat + ",\"longitude\":" + lon
                    + ",\"height\":" + height + ",\"simulationSeconds\":" + SimTimer.getTime() + "}");
                samples.flush();
                if (samples.checkError()) throw failure("Cannot write terrain samples");
            }
            return height;
        }
        @Override public synchronized double getElevationInterp(double lat, double lon) {
            if (!inside(lat, lon) || super.getTile(lat, lon) == null) throw failure("Unqualified bilinear query");
            return super.getElevationInterp(lat, lon);
        }
        @Override public synchronized double[] getInterceptPoint(double lat, double lon, double height,
                double heading, double slope, double distance, int level) {
            double[] result = super.getInterceptPoint(lat, lon, height, heading, slope, distance, level);
            intercepts++;
            if (rayCount < 512 && (intercepts <= 32 || intercepts % 512 == 0)) {
                rayCount++;
                rays.println("{\"input\":[" + lat + "," + lon + "," + height + "," + heading + "," + slope + "," + distance
                    + "],\"level\":" + level + ",\"result\":[" + result[0] + "," + result[1] + "," + result[2] + "]}");
                rays.flush();
                if (rays.checkError()) throw failure("Cannot write terrain rays");
            }
            return result;
        }
        synchronized void finish() {
            samples.close(); rays.close();
            StringBuilder calls = new StringBuilder();
            for (Map.Entry<String, Long> entry : counts.entrySet()) {
                if (calls.length() > 0) calls.append(',');
                calls.append('"').append(entry.getKey()).append("\":").append(entry.getValue());
            }
            try {
                Files.writeString(directory.resolve("terrain-summary.json"), "{\"queries\":" + queries
                    + ",\"intercepts\":" + intercepts + ",\"initializationPlaceholders\":" + initializationPlaceholders
                    + ",\"querySamples\":" + sampleCount + ",\"raySamples\":" + rayCount
                    + ",\"minimum\":" + minimum + ",\"maximum\":" + maximum + ",\"calls\":{" + calls + "}}", StandardCharsets.UTF_8);
            } catch (Exception error) { throw failure(error.toString()); }
        }
    }
}
